package app.mailpush.companion;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import org.json.JSONObject;
import org.unifiedpush.android.connector.FailedReason;
import org.unifiedpush.android.connector.PushService;
import org.unifiedpush.android.connector.data.PushEndpoint;
import org.unifiedpush.android.connector.data.PushMessage;
import java.net.URI;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import androidx.work.Data;
import androidx.work.BackoffPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.OneTimeWorkRequest;
import androidx.work.OutOfQuotaPolicy;
import androidx.work.WorkManager;
import java.util.concurrent.TimeUnit;

public final class MailPushService extends PushService {
    static final String CHANNEL = "mailpush_encrypted_alerts";

    @Override public void onNewEndpoint(PushEndpoint endpoint, String instance) {
        synchronized (Vault.LOCK) {
        try {
            Vault vault = new Vault(this); JSONObject profile = vault.get(instance);
            if (profile == null) return;
            URI url = new URI(endpoint.getUrl());
            if (endpoint.getTemporary() || endpoint.getPubKeySet() == null || !"https".equals(url.getScheme()) || url.getHost() == null || url.getRawUserInfo() != null || url.getFragment() != null) {
                profile.put("status", "A permanent HTTPS endpoint is required"); vault.put(profile); return;
            }
            JSONObject subscription = new JSONObject().put("endpoint", endpoint.getUrl()).put("keys", new JSONObject()
                .put("p256dh", endpoint.getPubKeySet().getPubKey()).put("auth", endpoint.getPubKeySet().getAuth()));
            String prior = profile.optString("endpoint_digest");
            profile.put("subscription", subscription);
            JSONObject bundle = MainActivity.bundle(profile);
            String digest = PairingCrypto.fingerprint(bundle);
            profile.put("endpoint_digest", digest);
            if (!prior.isEmpty() && !prior.equals(digest)) {
                profile.put("paired", false); profile.remove("pending_key"); profile.remove("source");
                profile.put("status", "Endpoint changed: export pairing again");
            } else profile.put("status", profile.optBoolean("paired") ? "Paired" : "Ready to export pairing");
            vault.put(profile);
        } catch (Exception ignored) { /* Never log endpoints, keys or payloads. */ }
        }
    }

    @Override public void onMessage(PushMessage message, String instance) {
        try {
            byte[] clear = message.getContent();
            if (!message.getDecrypted() || clear.length > 4096) return;
            if (!getSystemService(NotificationManager.class).areNotificationsEnabled() ||
                (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)) return;
            Vault vault = new Vault(this);
            JSONObject profile = vault.get(instance);
            if (profile == null || !profile.optBoolean("paired")) return;
            // UnifiedPush can invoke this callback on the main thread. Only
            // bounded local encryption happens here; native account I/O and
            // notification delivery run in a lifecycle-managed Android job.
            byte[] sealed = vault.sealWork(instance, clear);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(instance.getBytes(StandardCharsets.UTF_8)); digest.update((byte) 0);
            String name = "mailpush-alert-" + PairingCrypto.b64(digest.digest(clear));
            Data data = new Data.Builder().putString("instance", instance).putByteArray("sealed", sealed).build();
            OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(EncryptedAlertWorker.class)
                .setInputData(data).setBackoffCriteria(BackoffPolicy.LINEAR, 10, TimeUnit.SECONDS)
                .addTag("mailpush-profile-" + instance)
                .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST).build();
            WorkManager.getInstance(this).enqueueUniqueWork(name, ExistingWorkPolicy.KEEP, request);
        } catch (Exception ignored) { /* No plaintext job data, endpoints or exception details in logs. */ }
    }

    static void deliver(Context context, String instance, byte[] clear) {
        try {
            Vault vault = new Vault(context); JSONObject profile = vault.get(instance);
            long now = System.currentTimeMillis() / 1000;
            JSONObject event = EventPolicy.validate(clear, true, instance, profile, now);
            // A freshly checked signed-in account is required even if pairing is valid.
            // Account removal therefore rejects packets delivered during sign-out.
            if (!MailPushIntegration.ready(profile)) return;
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if ((Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) || !manager.areNotificationsEnabled()) return;
            synchronized (Vault.LOCK) {
            // The account query must never hold the vault lock: callbacks/UI
            // use that lock for short local operations. Re-read pairing after
            // the query so logout/re-pairing cannot race this final commit.
            profile = vault.get(instance);
            now = System.currentTimeMillis() / 1000;
            event = EventPolicy.validate(clear, true, instance, profile, now);
            try (Ledger ledger = new Ledger(context)) {
                if (!ledger.claim(instance, event.getString("event_id"), event.getLong("expires_at"), now)) return;
            }
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Encrypted alerts", NotificationManager.IMPORTANCE_HIGH));
            // Use the profile re-read under this lock, so a concurrent opt-out
            // cannot post another preview after its existing alerts are cleared.
            Notification notification = buildNotification(context, instance, event, profile);
            manager.notify(MailPushIntegration.tagPrefix(instance) + event.getString("event_id"), 0, notification);
            profile.put("last_alert", now); profile.put("status", "Encrypted alert received"); vault.put(profile);
            }
        } catch (Exception ignored) { /* Fail closed: invalid/unencrypted data never becomes a notification. */ }
    }

    /** Build only after deliver() has validated the bound, decrypted event. */
    static Notification buildNotification(Context context, String instance, JSONObject event, JSONObject profile) {
        NotificationPreview.Content generic = NotificationPreview.generic(event);
        NotificationPreview.Content content = NotificationPreview.content(event, profile);
        Intent open = new Intent(context, OpenMailActivity.class).putExtra("instance", instance)
            .setData(new android.net.Uri.Builder().scheme("mailpush-local").authority("open").appendPath(instance).build());
        PendingIntent action = PendingIntent.getActivity(context, instance.hashCode(), open,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        // The public version is constructed independently: preview fields,
        // account labels and expanded styles must never reach the redacted copy.
        Notification publicVersion = new Notification.Builder(context, CHANNEL)
            .setSmallIcon(MailPushIntegration.host().notificationIcon())
            .setContentTitle(generic.title).setContentText(generic.text)
            .setAllowSystemGeneratedContextualActions(false)
            .setVisibility(Notification.VISIBILITY_PUBLIC).build();
        Notification.Builder builder = new Notification.Builder(context, CHANNEL)
            .setSmallIcon(MailPushIntegration.host().notificationIcon())
            .setContentTitle(content.title).setContentText(content.text)
            .setPublicVersion(publicVersion).setVisibility(Notification.VISIBILITY_PRIVATE)
            .setAllowSystemGeneratedContextualActions(false)
            .setCategory(Notification.CATEGORY_EMAIL)
            .setContentIntent(action).setAutoCancel(true).setOnlyAlertOnce(true);
        if (content.preview) {
            builder.setStyle(new Notification.BigTextStyle().bigText(content.text));
            if (!content.accountLabel.isEmpty()) builder.setSubText(content.accountLabel);
        }
        // Android's notification/lock-screen policy controls visibility after
        // posting. Opting in shares these decrypted fields with Android and
        // authorized notification listeners, including while Proton is locked.
        return builder.build();
    }

    @Override public void onRegistrationFailed(FailedReason reason, String instance) { status(instance, "Registration failed; check your distributor"); }
    @Override public void onTempUnavailable(String instance) { status(instance, "Distributor temporarily unavailable"); }
    @Override public void onUnregistered(String instance) {
        synchronized (Vault.LOCK) {
        try {
            Vault vault = new Vault(this); JSONObject profile = vault.get(instance);
            if (profile != null) { profile.put("paired", false); profile.remove("subscription"); profile.remove("pending_key"); profile.remove("source"); profile.put("status", "Unregistered: register and pair again"); vault.put(profile); }
        } catch (Exception ignored) { }
        }
    }
    private void status(String instance, String text) {
        try { new Vault(this).update(instance, profile -> profile.put("status", text)); }
        catch (Exception ignored) { }
    }
}
