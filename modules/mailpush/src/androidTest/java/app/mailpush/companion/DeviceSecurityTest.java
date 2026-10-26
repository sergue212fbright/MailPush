package app.mailpush.companion;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.SystemClock;
import android.text.Spanned;
import android.view.ViewGroup;
import android.widget.ScrollView;
import androidx.lifecycle.Lifecycle;
import androidx.test.core.app.ActivityScenario;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Set;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONObject;
import org.json.JSONArray;
import org.junit.Before;
import org.junit.Test;
import org.junit.Assume;
import org.junit.runner.RunWith;
import org.unifiedpush.android.connector.UnifiedPush;
import org.unifiedpush.android.connector.keys.DefaultKeyManager;
import static org.junit.Assert.*;

/** Real Android Keystore/SQLite tests. The JVM test suite cannot substitute for these. */
@RunWith(AndroidJUnit4.class)
public class DeviceSecurityTest {
    private Context context;
    @Before public void setup() throws Exception {
        context = ApplicationProvider.getApplicationContext();
        File file = new File(context.getNoBackupFilesDir(), "mailpush-profiles.gcm");
        Files.deleteIfExists(file.toPath());
        Files.deleteIfExists(new File(file.getPath() + ".bak").toPath());
        context.deleteDatabase("mailpush-dedup.sqlite");
    }

    private DefaultKeyManager registerOffline(String instance) {
        // Connector 3.3.5 stores keys under a foreign key to its registration.
        // Use the same public registration path as the app, which inserts that
        // parent before generating real Android-backed keys. With no selected
        // distributor, its returned delivery registrations are empty: no IPC or
        // server is needed, and no synthetic distributor or weaker keys are used.
        assertNull("This fixture must remain offline without a distributor",
                UnifiedPush.getSavedDistributor(context));
        UnifiedPush.register(context, instance, "Synthetic device security test", null);
        DefaultKeyManager manager = new DefaultKeyManager(context);
        assertTrue("Public registration must create the recipient keys", manager.exists(instance));
        return manager;
    }

    @Test public void staleAuthorizationCannotRevealSettingsAfterAnotherResume() throws Exception {
        // Delay authorization deliberately, across a real Android pause/resume.
        // An unlocked result from an earlier resume must not expose setup while
        // the newest resume is still waiting for Proton's lock decision.
        Field hostField = MailPushIntegration.class.getDeclaredField("host");
        hostField.setAccessible(true);
        MailPushIntegration.Host previous = (MailPushIntegration.Host) hostField.get(null);
        List<Runnable> authorizations = new ArrayList<>(); // Accessed only on the UI thread.
        MailPushIntegration.install(new MailPushIntegration.Host() {
            @Override public List<MailPushIntegration.Account> accounts() {
                return java.util.Collections.emptyList();
            }
            @Override public int notificationIcon() { return android.R.drawable.ic_dialog_email; }
            @Override public boolean isAccountReady(String accountId) { return false; }
            @Override public void authorizeSettings(Activity activity, Runnable allowed) {
                authorizations.add(allowed);
            }
            @Override public void openInbox(Context context, String accountId) { }
        });
        MainActivity[] original = new MainActivity[1];
        Runnable[] earlierAuthorization = new Runnable[1];
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                original[0] = activity;
                assertFalse(authorizations.isEmpty());
                earlierAuthorization[0] = authorizations.get(authorizations.size() - 1);
                ViewGroup content = activity.findViewById(android.R.id.content);
                assertNotNull(content);
                assertEquals("Setup must start without rendered private content", 0, content.getChildCount());
            });
            scenario.moveToState(Lifecycle.State.STARTED);
            scenario.moveToState(Lifecycle.State.RESUMED);
            scenario.onActivity(activity -> {
                // Ensure this exercised another resume, not a replacement Activity
                // whose destroyed predecessor would already reject its callback.
                assertSame(original[0], activity);
                assertTrue("Resuming must request authorization again", authorizations.size() >= 2);
                ViewGroup content = activity.findViewById(android.R.id.content);
                earlierAuthorization[0].run();
                assertEquals("An earlier unlocked result must not authorize this resume", 0, content.getChildCount());
                authorizations.get(authorizations.size() - 1).run();
                assertTrue("The current authorized resume must render setup", content.getChildCount() > 0);
                assertTrue(content.getChildAt(0) instanceof ScrollView);
            });
        } finally {
            // The standalone harness normally has no Proton host. Restore that
            // exact state so another device test cannot inherit this fake gate.
            hostField.set(null, previous);
        }
    }

    @Test public void vaultRoundtripUsesAndroidKeystoreAndHidesPlaintext() throws Exception {
        String instance = UUID.randomUUID().toString();
        String secret = "SYNTHETIC-PAIRING-MATERIAL-NEVER-A-REAL-KEY";
        Vault vault = new Vault(context);
        vault.put(new JSONObject().put("instance", instance).put("account", "test-account").put("pending_key", secret));
        assertEquals(secret, new Vault(context).get(instance).getString("pending_key"));
        byte[] disk = Files.readAllBytes(new File(context.getNoBackupFilesDir(), "mailpush-profiles.gcm").toPath());
        assertFalse(new String(disk, StandardCharsets.ISO_8859_1).contains(secret));
        java.security.KeyStore store = java.security.KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        assertTrue(store.containsAlias("mailpush.profiles.v1"));
    }

    @Test public void vaultTamperingFailsClosed() throws Exception {
        Vault vault = new Vault(context);
        vault.put(new JSONObject().put("instance", UUID.randomUUID().toString()));
        File file = new File(context.getNoBackupFilesDir(), "mailpush-profiles.gcm");
        byte[] body = Files.readAllBytes(file.toPath()); body[body.length - 1] ^= 1; Files.write(file.toPath(), body);
        assertThrows(Exception.class, vault::all);
    }

    @Test public void queuedWorkIsEncryptedAndBoundToItsProfile() throws Exception {
        Vault vault = new Vault(context);
        String instance = UUID.randomUUID().toString();
        byte[] clear = "SYNTHETIC-ALERT-CONTENT".getBytes(StandardCharsets.UTF_8);
        byte[] sealed = vault.sealWork(instance,clear);
        assertFalse(new String(sealed,StandardCharsets.ISO_8859_1).contains("SYNTHETIC-ALERT"));
        assertArrayEquals(clear,vault.openWork(instance,sealed));
        assertThrows(Exception.class,()->vault.openWork(UUID.randomUUID().toString(),sealed));
        sealed[sealed.length-1] ^= 1;
        assertThrows(Exception.class,()->vault.openWork(instance,sealed));
    }

    @Test public void interruptedAtomicWriteRestoresExistingEncryptedBackup() throws Exception {
        String instance = UUID.randomUUID().toString();
        Vault vault = new Vault(context); vault.put(new JSONObject().put("instance",instance).put("account","synthetic"));
        File file = new File(context.getNoBackupFilesDir(), "mailpush-profiles.gcm");
        Files.move(file.toPath(), new File(file.getPath()+".bak").toPath());
        assertEquals("synthetic",new Vault(context).get(instance).getString("account"));
    }

    @Test public void unifiedPushKeysSurviveManagerRecreationAndCanBeDeleted() throws Exception {
        String instance = UUID.randomUUID().toString();
        try {
            DefaultKeyManager first = registerOffline(instance);
            String publicKey = first.getPublicKeySet(instance).getPubKey();
            DefaultKeyManager second = new DefaultKeyManager(context);
            assertTrue(second.exists(instance));
            assertEquals(publicKey, second.getPublicKeySet(instance).getPubKey());
            assertEquals(65, PairingCrypto.unb64(publicKey).length);
            second.delete(instance); assertFalse(new DefaultKeyManager(context).exists(instance));
        } finally {
            UnifiedPush.unregister(context, instance);
        }
    }

    @Test public void replayLedgerSurvivesReopenAndSeparatesProfiles() throws Exception {
        long now = System.currentTimeMillis()/1000;
        String event = UUID.randomUUID().toString(), profile = UUID.randomUUID().toString();
        try (Ledger first = new Ledger(context)) { assertTrue(first.claim(profile,event,now+300,now)); }
        try (Ledger second = new Ledger(context)) {
            assertFalse(second.claim(profile,event,now+300,now));
            assertTrue(second.claim(UUID.randomUUID().toString(),event,now+300,now));
        }
    }

    @Test public void signOutDeletesProfileAndRecipientKeysWithoutDistributor() throws Exception {
        String instance = UUID.randomUUID().toString();
        Vault vault = new Vault(context); vault.put(new JSONObject().put("instance",instance).put("account","gone"));
        try {
            DefaultKeyManager keys = registerOffline(instance);
            MailPushIntegration.reconcileAccounts(context,java.util.Collections.emptySet(),java.util.Collections.emptySet());
            assertNull(vault.get(instance)); assertFalse(keys.exists(instance));
        } finally {
            UnifiedPush.unregister(context, instance);
        }
    }

    private void installPreviewTestHost() {
        MailPushIntegration.install(new MailPushIntegration.Host() {
            @Override public List<MailPushIntegration.Account> accounts() { return java.util.Collections.emptyList(); }
            @Override public int notificationIcon() { return android.R.drawable.ic_dialog_email; }
            @Override public boolean isAccountReady(String accountId) { return "synthetic-account".equals(accountId); }
            @Override public void authorizeSettings(Activity activity, Runnable allowed) { allowed.run(); }
            @Override public void openInbox(Context context, String accountId) { }
        });
    }

    private JSONObject previewProfile(String instance) throws Exception {
        return new JSONObject().put("instance", instance).put("account", "synthetic-account")
            .put("label", "Synthetic private account").put("mailboxes", new JSONArray().put("personal"))
            .put("paired", true);
    }

    private JSONObject previewEvent() throws Exception {
        return new JSONObject().put("type", "new_mail").put("sender", "Synthetic private sender")
            .put("subject", "<b>Synthetic private subject</b>");
    }

    private void assertGenericNotification(Notification notification, String text) {
        assertEquals("Proton Mail", notification.extras.getCharSequence(Notification.EXTRA_TITLE).toString());
        assertEquals(text, notification.extras.getCharSequence(Notification.EXTRA_TEXT).toString());
        assertNull(notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT));
        assertNull(notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT));
        assertNull(notification.extras.getCharSequence(Notification.EXTRA_SUMMARY_TEXT));
        assertFalse(notification.getAllowSystemGeneratedContextualActions());
    }

    @Test public void previewNotificationsAlwaysHaveAnIndependentGenericPublicVersion() throws Exception {
        Field hostField = MailPushIntegration.class.getDeclaredField("host"); hostField.setAccessible(true);
        MailPushIntegration.Host previous = (MailPushIntegration.Host) hostField.get(null);
        installPreviewTestHost();
        try {
            String instance = UUID.randomUUID().toString();
            JSONObject profile = previewProfile(instance), event = previewEvent();
            Notification generic = MailPushService.buildNotification(context, instance, event, profile);
            assertGenericNotification(generic, "You have new mail");
            assertEquals(Notification.VISIBILITY_PRIVATE, generic.visibility);

            profile.put("show_previews", true);
            Notification rich = MailPushService.buildNotification(context, instance, event, profile);
            assertEquals(Notification.VISIBILITY_PRIVATE, rich.visibility);
            assertEquals("Synthetic private sender", rich.extras.getCharSequence(Notification.EXTRA_TITLE).toString());
            assertEquals("<b>Synthetic private subject</b>", rich.extras.getCharSequence(Notification.EXTRA_TEXT).toString());
            assertEquals("<b>Synthetic private subject</b>", rich.extras.getCharSequence(Notification.EXTRA_BIG_TEXT).toString());
            assertEquals("Synthetic private account", rich.extras.getCharSequence(Notification.EXTRA_SUB_TEXT).toString());
            assertFalse("Header markup must not become formatted text", rich.extras.getCharSequence(Notification.EXTRA_TEXT) instanceof Spanned);
            assertFalse(rich.getAllowSystemGeneratedContextualActions());
            assertNotNull(rich.publicVersion);
            assertNotSame(rich, rich.publicVersion);
            assertEquals(Notification.VISIBILITY_PUBLIC, rich.publicVersion.visibility);
            assertGenericNotification(rich.publicVersion, "You have new mail");

            event.put("type", "test");
            Notification test = MailPushService.buildNotification(context, instance, event, profile);
            assertGenericNotification(test, "Encrypted test received");
            assertGenericNotification(test.publicVersion, "Encrypted test received");
        } finally {
            hostField.set(null, previous);
        }
    }

    @Test public void previewChoiceRequiresCurrentAuthorizedResumedSettings() throws Exception {
        Field hostField = MailPushIntegration.class.getDeclaredField("host"); hostField.setAccessible(true);
        MailPushIntegration.Host previous = (MailPushIntegration.Host) hostField.get(null);
        installPreviewTestHost();
        String instance = UUID.randomUUID().toString();
        Vault vault = new Vault(context); vault.put(previewProfile(instance));
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                try {
                    assertFalse(NotificationPreview.enabled(vault.get(instance)));
                    assertTrue(activity.setPreviewsEnabled(instance, true));
                    assertTrue(NotificationPreview.enabled(new Vault(context).get(instance)));
                    assertTrue(activity.setPreviewsEnabled(instance, false));
                } catch (Exception error) { throw new AssertionError(error); }
            });
            scenario.moveToState(Lifecycle.State.STARTED);
            scenario.onActivity(activity -> {
                try {
                    assertFalse("A stale setup callback must not enable previews after pause",
                        activity.setPreviewsEnabled(instance, true));
                    assertFalse(NotificationPreview.enabled(new Vault(context).get(instance)));
                } catch (Exception error) { throw new AssertionError(error); }
            });
        } finally {
            hostField.set(null, previous);
        }
    }

    private void awaitNotification(NotificationManager manager, String tag, boolean expected) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + 5_000;
        boolean found;
        do {
            found = false;
            for (android.service.notification.StatusBarNotification notification : manager.getActiveNotifications()) {
                found |= tag.equals(notification.getTag());
            }
            if (found == expected) return;
            Thread.sleep(25);
        } while (SystemClock.elapsedRealtime() < deadline);
        assertEquals("Notification presence for synthetic profile", expected, found);
    }

    @Test public void optingOutCancelsExistingAlertsOnlyForThatProfile() throws Exception {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        // The disposable emulator runner grants POST_NOTIFICATIONS before this
        // test. A device that blocks notifications cannot exercise cancellation.
        Assume.assumeTrue("Grant notification permission to exercise live opt-out cancellation", manager.areNotificationsEnabled());
        Field hostField = MailPushIntegration.class.getDeclaredField("host"); hostField.setAccessible(true);
        MailPushIntegration.Host previous = (MailPushIntegration.Host) hostField.get(null);
        installPreviewTestHost();
        String instance = UUID.randomUUID().toString(), other = UUID.randomUUID().toString();
        String tag = MailPushIntegration.tagPrefix(instance) + UUID.randomUUID();
        String otherTag = MailPushIntegration.tagPrefix(other) + UUID.randomUUID();
        Vault vault = new Vault(context);
        JSONObject profile = previewProfile(instance).put("show_previews", true);
        JSONObject otherProfile = previewProfile(other).put("show_previews", true);
        vault.put(profile); vault.put(otherProfile);
        manager.createNotificationChannel(new NotificationChannel(MailPushService.CHANNEL, "Synthetic encrypted alerts", NotificationManager.IMPORTANCE_HIGH));
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            manager.notify(tag, 0, MailPushService.buildNotification(context, instance, previewEvent(), profile));
            manager.notify(otherTag, 0, MailPushService.buildNotification(context, other, previewEvent(), otherProfile));
            awaitNotification(manager, tag, true); awaitNotification(manager, otherTag, true);
            scenario.onActivity(activity -> assertTrue(activity.setPreviewsEnabled(instance, false)));
            awaitNotification(manager, tag, false);
            awaitNotification(manager, otherTag, true);
            assertFalse(NotificationPreview.enabled(new Vault(context).get(instance)));
            assertTrue(NotificationPreview.enabled(new Vault(context).get(other)));
            assertGenericNotification(MailPushService.buildNotification(context, instance, previewEvent(), vault.get(instance)), "You have new mail");
        } finally {
            manager.cancel(tag, 0); manager.cancel(otherTag, 0);
            hostField.set(null, previous);
        }
    }
}
