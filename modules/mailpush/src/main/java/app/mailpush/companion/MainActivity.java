package app.mailpush.companion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import org.unifiedpush.android.connector.UnifiedPush;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

public final class MainActivity extends Activity {
    private static final int EXPORT = 10, RECEIPT = 11;
    private static final int WHITE = Color.rgb(239, 246, 251), MUTED = Color.rgb(162, 180, 198), TEAL = Color.rgb(61, 214, 195);
    private Vault vault;
    private String pendingInstance;
    private ScrollView scroll;
    private boolean setupAuthorized;
    private boolean resumed;
    private long authorizationGeneration;
    private Intent deferredResult;
    private int deferredRequest, deferredCode;
    private AlertDialog privateDialog;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        vault = new Vault(this);
        if (state != null) pendingInstance = state.getString("pending_instance");
        // The host authorizes setup in onResume before any vault data is rendered.
    }

    @Override public void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state); state.putString("pending_instance", pendingInstance);
    }

    @Override public void onResume() {
        super.onResume();
        resumed = true;
        final long generation = ++authorizationGeneration;
        try {
            MailPushIntegration.host().authorizeSettings(this, () -> {
                if (!resumed || generation != authorizationGeneration || isFinishing() || isDestroyed()) return;
                setupAuthorized = true;
                render();
                if (deferredResult != null) {
                    Intent result = deferredResult; deferredResult = null;
                    handleResult(deferredRequest, deferredCode, result);
                }
            });
        } catch (Exception ignored) { finish(); }
    }
    @Override public void onPause() {
        resumed = false;
        ++authorizationGeneration; // Invalidate callbacks from every earlier resume.
        setupAuthorized = false;
        if (scroll != null) scroll.setVisibility(View.INVISIBLE);
        if (privateDialog != null) privateDialog.dismiss();
        super.onPause();
    }
    @Override public void onDestroy() { handler.removeCallbacksAndMessages(null); super.onDestroy(); }

    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }
    private LinearLayout column() { LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); return layout; }

    private TextView text(LinearLayout parent, String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        view.setPadding(0, dp(6), 0, dp(8)); parent.addView(view); return view;
    }

    private void button(LinearLayout parent, String label, View.OnClickListener click) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false);
        button.setTextColor(WHITE); button.setOnClickListener(click); parent.addView(button);
    }

    private void render() {
        if (!setupAuthorized || isFinishing() || isDestroyed()) return;
        int position = scroll == null ? 0 : scroll.getScrollY();
        scroll = new ScrollView(this);
        LinearLayout root = column(); root.setPadding(dp(22), dp(28), dp(22), dp(32)); scroll.addView(root);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                v.setPadding(dp(22) + bars.left, dp(18) + bars.top, dp(22) + bars.right, dp(22) + bars.bottom);
            } else v.setPadding(dp(22), dp(18) + insets.getSystemWindowInsetTop(), dp(22), dp(22) + insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(scroll);
        text(root, "Encrypted push", 34, WHITE).setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        text(root, "Your alerts. Your push service.", 18, TEAL);
        text(root, "Encrypted alerts inside your mail app. The push module never receives your Proton password or mail decryption keys.", 15, MUTED);
        try {
            String distributor = UnifiedPush.getSavedDistributor(this);
            text(root, "Push service: " + (distributor == null ? "choose one to begin" : appLabel(distributor)), 15, WHITE);
            button(root, "Choose push service", v -> chooseDistributor());
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                button(root, "Allow notifications", v -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20));
            JSONArray profiles = vault.all();
            for (int i = 0; i < profiles.length(); i++) card(root, profiles.getJSONObject(i));
            button(root, "Add a profile", v -> addProfile());
            button(root, "Refresh status", v -> render());
            text(root, "PRIVATE BY DEFAULT", 12, TEAL);
            text(root, "Your distributor handles push delivery. Notification private keys are wrapped with Android Keystore. Alerts are generic unless you enable previews for a profile. Proton Mail uses its own network connection for mail.", 14, MUTED);
            text(root, "Public push services still see delivery timing and IP addresses. Bridge and the connector must remain running.", 13, MUTED);
        } catch (Exception error) {
            text(root, "Secure storage is unavailable. Existing data has been preserved. Restart the phone and try again; reinstalling requires pairing again.", 15, WHITE);
        }
        scroll.post(() -> scroll.scrollTo(0, position));
    }

    private String appLabel(String packageName) {
        try { return getPackageManager().getApplicationLabel(getPackageManager().getApplicationInfo(packageName, 0)).toString(); }
        catch (PackageManager.NameNotFoundException ignored) { return packageName; }
    }

    private void card(LinearLayout parent, JSONObject profile) throws Exception {
        String instance = profile.getString("instance");
        LinearLayout card = column(); card.setPadding(dp(16), dp(12), dp(16), dp(16));
        GradientDrawable background = new GradientDrawable(); background.setColor(Color.rgb(24, 37, 55)); background.setCornerRadius(dp(16));
        background.setStroke(dp(1), Color.rgb(43, 63, 83)); card.setBackground(background);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2); layout.setMargins(0, dp(18), 0, dp(10)); parent.addView(card, layout);
        text(card, EventPolicy.safeText(profile.optString("label", "Profile")), 21, WHITE).setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        text(card, profile.optString("status", "Waiting for push service"), 14, TEAL);
        text(card, "Mailbox IDs: " + profile.getJSONArray("mailboxes").join(", ").replace("\"", ""), 13, MUTED);
        if (profile.optLong("last_alert") > 0) text(card, "Last alert: " + java.text.DateFormat.getDateTimeInstance().format(new java.util.Date(profile.getLong("last_alert") * 1000)), 13, MUTED);
        text(card, "Bound to a signed-in account", 13, MUTED);
        CheckBox previews = new CheckBox(this);
        previews.setText("Show sender and subject"); previews.setTextColor(WHITE);
        previews.setChecked(NotificationPreview.enabled(profile));
        previews.setOnCheckedChangeListener((view, enabled) -> {
            if (!setPreviewsEnabled(instance, enabled)) {
                fail("Could not change preview setting");
                render();
            }
        });
        card.addView(previews);
        text(card, "Previews require preview = true in the connector. Details are decrypted on this phone and shared with Android notifications, including when Proton Mail is locked. Android lock-screen privacy settings apply. Turning previews off clears this profile's current alerts.", 13, MUTED);
        if (profile.has("subscription")) {
            button(card, "1 · Export encrypted pairing request", v -> exportRequest(instance));
            if (profile.has("pending_key")) {
                button(card, "Show one-time pairing key", v -> showKey(instance));
                button(card, "2 · Import connector receipt", v -> {
                    pendingInstance = instance;
                    startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), RECEIPT);
                });
            }
        }
        button(card, "Register / reconnect", v -> register(instance));
        button(card, "Open Proton Mail", v -> startActivity(new Intent(this, OpenMailActivity.class).putExtra("instance", instance)));
        button(card, "Remove profile", v -> new AlertDialog.Builder(this).setTitle("Remove this profile?")
            .setMessage("This deletes its local pairing and notification keys. Revoke the device on the connector too if it will no longer be used.")
            .setNegativeButton("Keep", null).setPositiveButton("Remove", (dialog, which) -> remove(instance)).show());
    }

    /** Only a currently authorized setup screen may change this privacy choice. */
    boolean setPreviewsEnabled(String instance, boolean enabled) {
        if (!setupAuthorized || !resumed || isFinishing() || isDestroyed()) return false;
        synchronized (Vault.LOCK) {
            try {
                JSONObject current = vault.get(instance);
                if (current == null) return false;
                current.put("show_previews", enabled);
                vault.put(current);
                // Serialize opt-out with deliver()'s final profile read and post.
                // Queued jobs retain only ciphertext and will read the new flag.
                if (!enabled) MailPushIntegration.cancelAlerts(this, instance);
                return true;
            } catch (Exception ignored) { return false; }
        }
    }

    private void chooseDistributor() {
        List<String> choices = UnifiedPush.getDistributors(this);
        if (choices.isEmpty()) { fail("Install a UnifiedPush distributor such as the Google-free ntfy app, then return here"); return; }
        String[] labels = new String[choices.size()]; for (int i = 0; i < labels.length; i++) labels[i] = appLabel(choices.get(i));
        new AlertDialog.Builder(this).setTitle("Choose your push service").setItems(labels, (dialog, index) -> {
            try {
                String old = UnifiedPush.getSavedDistributor(this), selected = choices.get(index);
                if (old != null && !old.equals(selected) && vault.all().length() > 0) {
                    new AlertDialog.Builder(this).setTitle("Change push service?").setMessage("Existing profiles may need pairing again because their endpoints will change.")
                        .setNegativeButton("Keep current", null).setPositiveButton("Change", (d, w) -> selectDistributor(selected)).show();
                } else selectDistributor(selected);
            } catch (Exception ignored) { fail("Could not select push service"); }
        }).show();
    }

    private void selectDistributor(String selected) {
        try {
            UnifiedPush.saveDistributor(this, selected);
            JSONArray profiles = vault.all();
            for (int i = 0; i < profiles.length(); i++) register(profiles.getJSONObject(i).getString("instance"));
            render();
        } catch (Exception ignored) { fail("Could not select push service"); }
    }

    private void addProfile() {
        if (UnifiedPush.getSavedDistributor(this) == null) { chooseDistributor(); return; }
        java.util.List<MailPushIntegration.Account> accounts = MailPushIntegration.host().accounts();
        if (accounts.isEmpty()) { fail("Sign into a mail account before pairing"); return; }
        LinearLayout form = column(); form.setPadding(dp(20), 0, dp(20), 0);
        Spinner account = new Spinner(this);
        String[] labels = new String[accounts.size()];
        for (int i = 0; i < labels.length; i++) labels[i] = accounts.get(i).label;
        account.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels)); form.addView(account);
        EditText boxes = new EditText(this); boxes.setHint("Mailbox IDs, e.g. personal"); boxes.setText("personal"); boxes.setSingleLine(true); form.addView(boxes);
        EditText vapid = new EditText(this); vapid.setHint("Optional provider VAPID public key"); vapid.setSingleLine(true); form.addView(vapid);
        text(form, "Use the same mailbox IDs in the connector. This account binding stays only on this phone.", 13, MUTED);
        AlertDialog accountDialog = new AlertDialog.Builder(this).setTitle("Bind encrypted alerts").setView(form).setNegativeButton("Cancel", null).setPositiveButton("Create", (dialog, which) -> {
            try {
                Set<String> allowed = new LinkedHashSet<>();
                for (String item : boxes.getText().toString().split(",")) {
                    String id = item.trim(); if (!id.matches("[A-Za-z0-9_-]{1,48}")) throw new IllegalArgumentException(); allowed.add(id);
                }
                if (allowed.isEmpty() || allowed.size() > 32) throw new IllegalArgumentException();
                String publicKey = vapid.getText().toString().trim();
                if (!publicKey.isEmpty() && !publicKey.matches("[A-Za-z0-9_-]{87}")) throw new IllegalArgumentException();
                MailPushIntegration.Account selected = accounts.get(account.getSelectedItemPosition());
                JSONObject profile = new JSONObject().put("instance", UUID.randomUUID().toString())
                    .put("account", selected.id).put("label", selected.label)
                    .put("mailboxes", new JSONArray(allowed)).put("paired", false)
                    .put("show_previews", false)
                    .put("vapid", publicKey).put("status", "Registering with push service");
                vault.put(profile); register(profile.getString("instance")); render();
            } catch (Exception ignored) { fail("Use 1–32 simple mailbox IDs and a valid optional VAPID key"); }
        }).create();
        privateDialog = accountDialog;
        if (accountDialog.getWindow() != null) accountDialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        accountDialog.show();
    }

    private void register(String instance) {
        try {
            JSONObject profile = vault.get(instance); if (profile == null) return;
            if (UnifiedPush.getSavedDistributor(this) == null) { chooseDistributor(); return; }
            UnifiedPush.register(this, instance, "MailPush", profile.optString("vapid").isEmpty() ? null : profile.getString("vapid"));
            handler.postDelayed(this::render, 1500);
        } catch (Exception ignored) { fail("Registration failed; check your selected push service"); }
    }

    static JSONObject bundle(JSONObject profile) throws Exception {
        JSONObject subscription = profile.getJSONObject("subscription");
        return new JSONObject().put("format", "mailpush-receiver-v2").put("binding", profile.getString("instance"))
            .put("mailboxes", profile.getJSONArray("mailboxes")).put("endpoint", subscription.getString("endpoint"))
            .put("keys", subscription.getJSONObject("keys")).put("created_at", System.currentTimeMillis() / 1000);
    }

    private void exportRequest(String instance) {
        synchronized (Vault.LOCK) {
        byte[] key = null;
        try {
            JSONObject profile = vault.get(instance); if (profile == null || !profile.has("subscription")) return;
            key = PairingCrypto.random(32); JSONObject request = bundle(profile);
            profile.put("pending_key", PairingCrypto.b64(key)).put("pending_request", PairingCrypto.b64(PairingCrypto.export(request, key)))
                .put("pending_fingerprint", PairingCrypto.fingerprint(request)).put("pending_at", System.currentTimeMillis() / 1000);
            vault.put(profile); pendingInstance = instance;
            startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/octet-stream")
                .putExtra(Intent.EXTRA_TITLE, "mailpush-" + instance.substring(0, 8) + ".mailpush"), EXPORT);
        } catch (Exception ignored) { fail("Could not create encrypted pairing request"); }
        finally { if (key != null) Arrays.fill(key, (byte) 0); }
        }
    }

    private void showKey(String instance) {
        try {
            JSONObject profile = vault.get(instance); if (profile == null || !profile.has("pending_key")) return;
            if (System.currentTimeMillis() / 1000 - profile.getLong("pending_at") > 86400) { fail("Pairing expired. Export a fresh request"); return; }
            TextView key = new TextView(this); key.setPadding(dp(24), dp(16), dp(24), dp(16)); key.setTextSize(16); key.setTypeface(Typeface.MONOSPACE);
            key.setText(profile.getString("pending_key") + "\n\nFingerprint\n" + profile.getString("pending_fingerprint")); key.setTextIsSelectable(true);
            AlertDialog dialog = new AlertDialog.Builder(this).setTitle("One-time pairing key")
                .setMessage("Enter this in the connector's hidden prompt. Keep it separate from the encrypted request. Import the returned receipt to finish pairing.")
                .setView(key).setPositiveButton("Done", null).create();
            privateDialog = dialog;
            if (dialog.getWindow() != null) dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            dialog.show();
        } catch (Exception ignored) { fail("Could not read pairing key"); }
    }

    @Override public void onActivityResult(int requestCode, int resultCode, Intent result) {
        super.onActivityResult(requestCode, resultCode, result);
        // Document providers can return while Proton has auto-locked. Defer all
        // decrypt/export operations until the host authorizes the resumed screen.
        if (!setupAuthorized) {
            deferredRequest = requestCode; deferredCode = resultCode; deferredResult = result;
            return;
        }
        handleResult(requestCode, resultCode, result);
    }

    private void handleResult(int requestCode, int resultCode, Intent result) {
        if (resultCode != RESULT_OK || result == null || result.getData() == null || pendingInstance == null) return;
        try {
            JSONObject profile = vault.get(pendingInstance); if (profile == null || !profile.has("pending_key")) return;
            if (requestCode == EXPORT) {
                try (OutputStream output = getContentResolver().openOutputStream(result.getData())) {
                    if (output == null) throw new IllegalStateException();
                    output.write(PairingCrypto.unb64(profile.getString("pending_request")));
                }
                render(); showKey(pendingInstance);
            } else if (requestCode == RECEIPT) {
                byte[] bytes;
                try (InputStream input = getContentResolver().openInputStream(result.getData()); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    if (input == null) throw new IllegalStateException();
                    byte[] chunk = new byte[1024]; int read;
                    while ((read = input.read(chunk)) != -1) { if (output.size() + read > 65536) throw new SecurityException(); output.write(chunk, 0, read); }
                    bytes = output.toByteArray();
                }
                importReceipt(profile, bytes); render();
                Toast.makeText(this, "Pairing complete. Send an encrypted test from the connector.", Toast.LENGTH_LONG).show();
            }
        } catch (Exception ignored) { fail("Pairing file could not be verified. Check the file and export a fresh request if needed"); }
    }

    private void importReceipt(JSONObject profile, byte[] bytes) throws Exception {
        vault.update(profile.getString("instance"), current -> {
            JSONObject receipt = PairingCrypto.verifyReceipt(current, bytes, System.currentTimeMillis() / 1000);
            current.put("source", receipt.getString("source")).put("paired", true).put("status", "Paired · waiting for encrypted alerts");
            current.remove("pending_key"); current.remove("pending_request"); current.remove("pending_fingerprint"); current.remove("pending_at");
        });
    }

    private void remove(String instance) {
        synchronized (Vault.LOCK) {
        try {
            // Local revocation must succeed even when distributor IPC fails.
            // Delete the profile before any late registration/message callback.
            vault.remove(instance);
            MailPushIntegration.cancelQueued(this, instance);
            try { new org.unifiedpush.android.connector.keys.DefaultKeyManager(this).delete(instance); }
            catch (Exception ignored) { }
            try { UnifiedPush.unregister(this, instance); } catch (Exception ignored) { }
            try { MailPushIntegration.cancelAlerts(this, instance); } catch (Exception ignored) { }
            render();
        } catch (Exception ignored) { fail("Could not remove profile"); }
        }
    }

    private void fail(String message) { new AlertDialog.Builder(this).setTitle("MailPush").setMessage(message).setPositiveButton("OK", null).show(); }
}
