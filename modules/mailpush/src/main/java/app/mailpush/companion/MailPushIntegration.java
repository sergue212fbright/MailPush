package app.mailpush.companion;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.Context;
import java.util.List;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;
import org.unifiedpush.android.connector.UnifiedPush;

/**
 * The entire Proton-facing contract. The receiver deliberately knows no Proton
 * tokens, mailbox databases, Rust types or navigation classes. Only the adapter
 * implements this interface; upstream API changes are confined to that file.
 */
public final class MailPushIntegration {
    public static final class Account {
        public final String id;
        public final String label;
        public Account(String id, String label) { this.id = id; this.label = label; }
    }

    public interface Host {
        /** Snapshot for the setup UI; account IDs never leave the encrypted local vault. */
        List<Account> accounts();
        /** Native host icon; avoids copying or importing Proton resources into this module. */
        int notificationIcon();
        /** Fresh, bounded account check. Called on the receiver/background thread. */
        boolean isAccountReady(String accountId);
        /** Apply Proton's own app-lock policy before exposing setup keys or account labels. */
        void authorizeSettings(Activity activity, Runnable allowed);
        /** Select the bound account and enter the host's normal lock/navigation path. */
        void openInbox(Context context, String accountId);
    }

    private static volatile Host host;
    private MailPushIntegration() { }
    static boolean initialized() { return host != null; }
    public static void install(Host implementation) {
        if (implementation == null) throw new IllegalArgumentException("Host required");
        host = implementation;
    }
    static Host host() {
        Host value = host;
        if (value == null) throw new IllegalStateException("Mail host is not initialized");
        return value;
    }
    static String tagPrefix(String instance) { return "mailpush:" + instance + ":"; }
    static boolean ready(JSONObject profile) {
        try { return profile != null && host().isAccountReady(profile.getString("account")); }
        catch (Exception ignored) { return false; } // Account/adapter errors never expose an alert.
    }
    static void cancelAlerts(Context context, String instance) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        for (android.service.notification.StatusBarNotification item : manager.getActiveNotifications()) {
            String tag = item.getTag();
            if (tag != null && tag.startsWith(tagPrefix(instance))) manager.cancel(tag, item.getId());
        }
    }

    static void cancelQueued(Context context, String instance) {
        try { androidx.work.WorkManager.getInstance(context).cancelAllWorkByTag("mailpush-profile-" + instance); }
        catch (Exception ignored) { } // Missing profile still rejects any already-running job.
    }

    /**
     * Called only with a successful native account read, never an observer's
     * seeded-empty/error snapshot. NotReady
     * accounts retain their keys, but cannot display alerts; logout/removal wipes
     * the profile, unregisters delivery and removes already displayed previews.
     */
    public static void reconcileAccounts(Context context, Set<String> present, Set<String> disabled) {
        synchronized (Vault.LOCK) {
            try {
                Vault vault = new Vault(context);
                JSONArray profiles = vault.all();
                for (int i = 0; i < profiles.length(); i++) {
                    JSONObject profile = profiles.getJSONObject(i);
                    String account = profile.optString("account", "");
                    if (!present.contains(account) || disabled.contains(account)) {
                        String instance = profile.getString("instance");
                        // Revoke locally first: a late distributor callback cannot restore pairing.
                        vault.remove(instance);
                        cancelQueued(context, instance);
                        try { cancelAlerts(context, instance); } catch (Exception ignored) { }
                        // Key deletion must not depend on a distributor being alive.
                        try { new org.unifiedpush.android.connector.keys.DefaultKeyManager(context).delete(instance); }
                        catch (Exception ignored) { }
                        try { UnifiedPush.unregister(context, instance); } catch (Exception ignored) { }
                        // Continue cleanup of other accounts even if one IPC call fails.
                    }
                }
            } catch (Exception ignored) { /* No account IDs, keys or payloads in logs. */ }
        }
    }
}
