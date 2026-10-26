/* SPDX-License-Identifier: GPL-3.0-or-later
 * MailPush contributors. This file is the only adapter to Proton's internal APIs.
 */
package ch.protonmail.android.mailpush

import android.app.Activity
import android.content.Context
import android.content.Intent
import app.mailpush.companion.MailPushIntegration
import ch.protonmail.android.mailpinlock.domain.AutoLockRepository
import ch.protonmail.android.mailsession.data.repository.MailSessionRepository
import ch.protonmail.android.mailsession.domain.model.AccountState
import ch.protonmail.android.mailsession.domain.repository.UserSessionRepository
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.retryWhen
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import me.proton.core.domain.entity.UserId
import uniffi.mail_uniffi.MailSessionGetAccountsResult
import uniffi.mail_uniffi.StoredAccountState

/**
 * The receiver never receives Proton sessions, passwords or mail keys. A narrow
 * host interface supplies account readiness, the existing app-lock gate, and
 * navigation. If an upstream API changes, this adapter should fail compilation.
 */
object MailPushInitializer {
    /** Called by Proton's existing ordered MainInitializer after its dependencies. */
    fun install(context: Context) {
        val app = context.applicationContext
        val deps = EntryPointAccessors.fromApplication(app, Dependencies::class.java)
        val sessions = deps.mailPushSessions()
        val mailSession = deps.mailPushSessionRepository()
        val lock = deps.mailPushAppLock()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        val ready = AtomicReference<List<MailPushIntegration.Account>>(emptyList())

        MailPushIntegration.install(object : MailPushIntegration.Host {
            override fun accounts(): List<MailPushIntegration.Account> = ready.get()

            override fun notificationIcon(): Int =
                ch.protonmail.android.mailcommon.presentation.R.drawable.ic_proton_brand_proton_mail

            override fun isAccountReady(accountId: String): Boolean = try {
                // Runs on the push service's worker thread, never on a UI callback.
                // Fresh state prevents an observer timing race during logout.
                runBlocking(Dispatchers.IO) {
                    withTimeout(5_000) { sessions.getAccount(UserId(accountId))?.state == AccountState.Ready }
                }
            } catch (_: Exception) { false }

            override fun authorizeSettings(activity: Activity, allowed: Runnable) {
                scope.launch {
                    val locked = try {
                        withContext(Dispatchers.IO) {
                            withTimeout(5_000) { lock.shouldAutoLock().fold({ true }, { it }) }
                        }
                    } catch (_: Exception) { true }
                    if (activity.isFinishing || activity.isDestroyed) return@launch
                    if (locked) {
                        // Return to the existing Proton activity, which owns
                        // PIN/biometric verification. Never bring a backgrounded
                        // app forward just because an async settings check ended.
                        activity.finish()
                    } else allowed.run()
                }
            }

            override fun openInbox(context: Context, accountId: String) {
                scope.launch {
                    val valid = try {
                        withContext(Dispatchers.IO) {
                            withTimeout(5_000) {
                                if (sessions.getAccount(UserId(accountId))?.state != AccountState.Ready) false
                                else { sessions.setPrimaryAccount(UserId(accountId)); true }
                            }
                        }
                    } catch (_: Exception) { false }
                    if (valid) launchMail(app)
                }
            }
        })

        scope.launch(Dispatchers.IO) {
            // observeAccounts is a change signal, not deletion authority: upstream
            // seeds it with an empty list and also emits empty lists on SDK errors.
            // Only a successful fresh native query can revoke stored pairings.
            sessions.observeAccounts().retryWhen { _, attempt ->
                ready.set(emptyList())
                // A transient observer failure must not permanently disable
                // later logout cleanup, or spin a CPU/logging retry loop.
                delay(1_000L * (attempt.coerceAtMost(59) + 1))
                true
            }.collect { accounts ->
                ready.set(accounts.filter { it.state == AccountState.Ready }.map {
                    MailPushIntegration.Account(it.userId.id, it.primaryAddress)
                })
                try {
                    val snapshot = withTimeout(5_000) {
                        mailSession.getMailSession().getRustMailSession().getAccounts()
                    }
                    if (snapshot is MailSessionGetAccountsResult.Ok) {
                        val stored = snapshot.v1
                        MailPushIntegration.reconcileAccounts(
                            app, stored.map { it.userId() }.toSet(),
                            stored.filter { it.state() is StoredAccountState.LoggedOut }
                                .map { it.userId() }.toSet()
                        )
                    } else {
                        ready.set(emptyList())
                    }
                } catch (_: Exception) {
                    // A timeout/read failure preserves keys but disables setup
                    // choices until another successful account update arrives.
                    ready.set(emptyList())
                }
            }
        }
    }

    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface Dependencies {
        fun mailPushSessions(): UserSessionRepository
        fun mailPushSessionRepository(): MailSessionRepository
        fun mailPushAppLock(): AutoLockRepository
    }
}

private fun launchMail(context: Context) {
    // Resolve only this APK's launch activity. No hard-coded official package,
    // external URLs, message-provided intents, or bypass of Proton's app lock.
    context.packageManager.getLaunchIntentForPackage(context.packageName)?.let {
        context.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
    }
}
