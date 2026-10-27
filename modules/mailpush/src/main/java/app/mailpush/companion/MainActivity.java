package app.mailpush.companion;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import org.unifiedpush.android.connector.UnifiedPush;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Settings UI for the independent receiver. Proton integration stays in Host. */
public final class MainActivity extends Activity {
    private static final int EXPORT = 10, RECEIPT = 11;
    private Vault vault;
    private SettingsUi ui;
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
        ui = new SettingsUi(this);
        vault = new Vault(this);
        if (state != null) pendingInstance = state.getString("pending_instance");
        // Do not inflate account data before the host's existing lock check.
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
        ++authorizationGeneration;
        setupAuthorized = false;
        if (scroll != null) scroll.setVisibility(View.INVISIBLE);
        if (privateDialog != null) privateDialog.dismiss();
        super.onPause();
    }

    @Override public void onDestroy() { handler.removeCallbacksAndMessages(null); super.onDestroy(); }

    private boolean authorized() {
        return setupAuthorized && resumed && !isFinishing() && !isDestroyed();
    }
    private String s(int id, Object... args) { return getString(id, args); }
    private int dp(int value) { return ui.dp(value); }
    private LinearLayout column() { return ui.column(); }

    /** Every private dialog follows the same authorization and background policy. */
    private void showPrivate(AlertDialog dialog) {
        if (!authorized()) return;
        if (privateDialog != null) privateDialog.dismiss();
        privateDialog = dialog;
        if (dialog.getWindow() != null) dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        dialog.show();
    }

    private void render() {
        if (!authorized()) return;
        int position = scroll == null ? 0 : scroll.getScrollY();
        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(ui.backgroundColor());
        LinearLayout root = column();
        root.setPadding(dp(16), dp(16), dp(16), dp(24));
        scroll.addView(root);
        // Keep inset handling local. In particular, content must not slide under
        // Android 15's edge-to-edge status bar when the page is scrolled.
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            } else v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        setContentView(scroll);
        scroll.requestApplyInsets();
        toolbar(root);
        ui.text(root, s(R.string.mailpush_intro), 14, ui.mutedColor());
        ui.gap(root, 12);
        try {
            serviceCard(root);
            JSONArray profiles = vault.all();
            ui.section(root, s(R.string.mailpush_accounts));
            if (profiles.length() == 0) {
                LinearLayout empty = ui.card(root);
                ui.text(empty, s(R.string.mailpush_empty_title), 18, ui.textColor()).setTypeface(Typeface.DEFAULT, Typeface.BOLD);
                ui.text(empty, s(R.string.mailpush_empty_body), 14, ui.mutedColor());
            }
            for (int i = 0; i < profiles.length(); i++) card(root, profiles.getJSONObject(i));
            ui.button(root, s(R.string.mailpush_add_account), "mailpush.add_account", true, v -> addProfile());
            ui.gap(root, 12);
            ui.textAction(root, s(R.string.mailpush_refresh), "mailpush.refresh", v -> render());
            ui.text(root, s(R.string.mailpush_footer), 13, ui.mutedColor());
            ui.textAction(root, s(R.string.mailpush_privacy_details), "mailpush.privacy", v -> showPrivacy());
        } catch (Exception error) {
            LinearLayout errorCard = ui.card(root);
            ui.text(errorCard, s(R.string.mailpush_storage_unavailable), 15, ui.textColor());
        }
        scroll.post(() -> scroll.scrollTo(0, position));
    }

    private void toolbar(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        ImageButton back = new ImageButton(this);
        back.setImageResource(R.drawable.mailpush_ic_back);
        back.setImageTintList(ColorStateList.valueOf(ui.textColor()));
        back.setBackgroundResource(android.R.drawable.list_selector_background);
        back.setContentDescription(s(R.string.mailpush_back));
        back.setTag("mailpush.back");
        back.setOnClickListener(v -> finish());
        row.addView(back, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView title = new TextView(this);
        title.setText(s(R.string.mailpush_settings_title));
        title.setTextColor(ui.textColor()); title.setTextSize(22);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setPadding(dp(8), 0, 0, 0);
        row.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        parent.addView(row, new LinearLayout.LayoutParams(-1, -2));
        ui.gap(parent, 12);
    }

    private void serviceCard(LinearLayout parent) {
        String distributor = UnifiedPush.getSavedDistributor(this);
        LinearLayout service = ui.card(parent);
        ui.text(service, s(R.string.mailpush_push_service), 13, ui.mutedColor());
        ui.text(service, distributor == null ? s(R.string.mailpush_service_missing) : appLabel(distributor), 18, ui.textColor())
                .setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        ui.text(service, s(distributor == null ? R.string.mailpush_service_help : R.string.mailpush_service_selected), 14, ui.mutedColor());
        ui.button(service, s(distributor == null ? R.string.mailpush_choose_service : R.string.mailpush_change_service),
                "mailpush.choose_service", distributor == null, v -> chooseDistributor());
        NotificationManager notifications = getSystemService(NotificationManager.class);
        if (notifications != null && !notifications.areNotificationsEnabled()) {
            ui.divider(service);
            ui.text(service, s(R.string.mailpush_notifications_off), 15, ui.textColor());
            ui.button(service, s(R.string.mailpush_allow_notifications), "mailpush.allow_notifications", true, v -> {
                if (!authorized()) return;
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                    requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
                else startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
            });
        }
    }

    private String appLabel(String packageName) {
        try { return getPackageManager().getApplicationLabel(getPackageManager().getApplicationInfo(packageName, 0)).toString(); }
        catch (PackageManager.NameNotFoundException ignored) { return packageName; }
    }

    private void card(LinearLayout parent, JSONObject profile) throws Exception {
        String instance = profile.getString("instance");
        boolean paired = profile.optBoolean("paired"), pending = profile.has("pending_key");
        LinearLayout card = ui.card(parent);
        TextView label = ui.text(card, EventPolicy.safeText(profile.optString("label", s(R.string.mailpush_account_fallback))), 19, ui.textColor());
        label.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        ui.badge(card, s(paired ? R.string.mailpush_paired : R.string.mailpush_setup_needed));
        if (paired) {
            long lastAlert = profile.optLong("last_alert");
            ui.text(card, lastAlert > 0 ? s(R.string.mailpush_last_alert,
                    java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT)
                            .format(new java.util.Date(lastAlert * 1000))) : s(R.string.mailpush_waiting_first_alert), 13, ui.mutedColor());
        }
        if (!paired || pending) pairingSteps(card, profile);
        ui.divider(card);
        Switch previews = new Switch(this);
        previews.setText(s(R.string.mailpush_preview_title));
        previews.setTextColor(ui.textColor()); previews.setTextSize(16);
        previews.setMinHeight(dp(56)); previews.setSwitchPadding(dp(16));
        previews.setPadding(0, dp(4), 0, dp(4));
        previews.setTag("mailpush.preview." + instance);
        previews.setChecked(NotificationPreview.enabled(profile));
        previews.setOnCheckedChangeListener((view, enabled) -> {
            if (!setPreviewsEnabled(instance, enabled)) {
                fail(s(R.string.mailpush_preview_failed)); render();
            }
        });
        card.addView(previews, new LinearLayout.LayoutParams(-1, -2));
        ui.text(card, s(R.string.mailpush_preview_summary), 13, ui.mutedColor());
        ui.textAction(card, s(R.string.mailpush_preview_details), "mailpush.preview_info." + instance,
                v -> showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_preview_title)
                        .setMessage(R.string.mailpush_preview_explanation).setPositiveButton(R.string.mailpush_done, null).create()));
        accountOptions(card, profile);
    }

    private void pairingSteps(LinearLayout card, JSONObject profile) throws Exception {
        String instance = profile.getString("instance");
        if (!profile.has("subscription")) {
            ui.text(card, s(R.string.mailpush_waiting_service), 14, ui.mutedColor());
            ui.button(card, s(R.string.mailpush_retry_service), "mailpush.register." + instance, true, v -> register(instance));
            return;
        }
        boolean pending = profile.has("pending_key");
        ui.gap(card, 8);
        ui.text(card, s(pending ? R.string.mailpush_pairing_finish : R.string.mailpush_pairing_begin), 16, ui.textColor())
                .setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        ui.text(card, s(pending ? R.string.mailpush_pairing_pending_help : R.string.mailpush_pairing_export_help), 14, ui.mutedColor());
        ui.button(card, s(pending ? R.string.mailpush_export_fresh : R.string.mailpush_export), "mailpush.export." + instance,
                !pending, v -> exportRequest(instance));
        if (pending) {
            ui.button(card, s(R.string.mailpush_show_key), "mailpush.key." + instance, false, v -> showKey(instance));
            ui.button(card, s(R.string.mailpush_import), "mailpush.import." + instance, true, v -> importReceiptFile(instance));
        }
    }

    private void importReceiptFile(String instance) {
        if (!authorized()) return;
        pendingInstance = instance;
        startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), RECEIPT);
    }

    private void accountOptions(LinearLayout card, JSONObject profile) throws Exception {
        String instance = profile.getString("instance");
        LinearLayout options = column();
        options.setVisibility(View.GONE);
        ui.textAction(card, s(R.string.mailpush_account_options), "mailpush.options." + instance, v -> {
            boolean expanded = options.getVisibility() != View.VISIBLE;
            options.setVisibility(expanded ? View.VISIBLE : View.GONE);
            ((Button) v).setText(s(expanded ? R.string.mailpush_hide_options : R.string.mailpush_account_options));
        });
        card.addView(options, new LinearLayout.LayoutParams(-1, -2));
        ui.text(options, s(R.string.mailpush_mailbox_details,
                profile.getJSONArray("mailboxes").join(", ").replace("\"", "")), 13, ui.mutedColor());
        ui.text(options, s(R.string.mailpush_status_details, EventPolicy.safeText(profile.optString("status", ""))), 13, ui.mutedColor());
        ui.button(options, s(R.string.mailpush_reconnect), "mailpush.reconnect." + instance, false, v -> register(instance));
        if (profile.optBoolean("paired") && !profile.has("pending_key") && profile.has("subscription")) {
            ui.button(options, s(R.string.mailpush_pair_again), "mailpush.export." + instance, false,
                    v -> showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_pair_again)
                            .setMessage(R.string.mailpush_pair_again_help).setNegativeButton(R.string.mailpush_cancel, null)
                            .setPositiveButton(R.string.mailpush_continue, (d, w) -> exportRequest(instance)).create()));
        }
        Button remove = ui.button(options, s(R.string.mailpush_remove_account), "mailpush.remove." + instance, false,
                v -> showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_remove_title)
                        .setMessage(R.string.mailpush_remove_explanation).setNegativeButton(R.string.mailpush_keep, null)
                        .setPositiveButton(R.string.mailpush_remove, (d, w) -> remove(instance)).create()));
        remove.setTextColor(ui.dangerColor());
    }

    private void showPrivacy() {
        showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_privacy_details)
                .setMessage(R.string.mailpush_privacy_explanation).setPositiveButton(R.string.mailpush_done, null).create());
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
        if (!authorized()) return;
        List<String> choices = UnifiedPush.getDistributors(this);
        if (choices.isEmpty()) { fail(s(R.string.mailpush_install_service)); return; }
        String[] labels = new String[choices.size()];
        for (int i = 0; i < labels.length; i++) labels[i] = appLabel(choices.get(i));
        showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_choose_service).setItems(labels, (dialog, index) -> {
            if (!authorized()) return;
            try {
                String old = UnifiedPush.getSavedDistributor(this), selected = choices.get(index);
                if (old != null && !old.equals(selected) && vault.all().length() > 0) {
                    showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_change_service_title)
                            .setMessage(R.string.mailpush_change_service_explanation).setNegativeButton(R.string.mailpush_keep_current, null)
                            .setPositiveButton(R.string.mailpush_change, (d, w) -> selectDistributor(selected)).create());
                } else selectDistributor(selected);
            } catch (Exception ignored) { fail(s(R.string.mailpush_service_failed)); }
        }).create());
    }

    private void selectDistributor(String selected) {
        if (!authorized()) return;
        try {
            UnifiedPush.saveDistributor(this, selected);
            JSONArray profiles = vault.all();
            for (int i = 0; i < profiles.length(); i++) register(profiles.getJSONObject(i).getString("instance"));
            render();
        } catch (Exception ignored) { fail(s(R.string.mailpush_service_failed)); }
    }

    private void addProfile() {
        if (!authorized()) return;
        if (UnifiedPush.getSavedDistributor(this) == null) { chooseDistributor(); return; }
        List<MailPushIntegration.Account> accounts = MailPushIntegration.host().accounts();
        if (accounts.isEmpty()) { fail(s(R.string.mailpush_sign_in_first)); return; }
        LinearLayout form = column(); form.setPadding(dp(24), dp(8), dp(24), dp(16));
        form.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        ScrollView formScroll = new ScrollView(this); formScroll.addView(form);
        TextView accountLabel = ui.text(form, s(R.string.mailpush_account_label), 14, ui.textColor());
        Spinner account = new Spinner(this); account.setId(View.generateViewId()); accountLabel.setLabelFor(account.getId());
        account.setMinimumHeight(dp(48)); account.setTag("mailpush.account_picker");
        String[] labels = new String[accounts.size()];
        for (int i = 0; i < labels.length; i++) labels[i] = accounts.get(i).label;
        account.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
        form.addView(account, new LinearLayout.LayoutParams(-1, -2));
        TextView boxesLabel = ui.text(form, s(R.string.mailpush_mailbox_label), 14, ui.textColor());
        EditText boxes = new EditText(this); boxes.setId(View.generateViewId()); boxesLabel.setLabelFor(boxes.getId());
        boxes.setText("personal"); boxes.setHint(R.string.mailpush_mailbox_hint); boxes.setTag("mailpush.mailbox_ids");
        ui.field(boxes); form.addView(boxes, new LinearLayout.LayoutParams(-1, -2));
        ui.text(form, s(R.string.mailpush_mailbox_help), 13, ui.mutedColor());
        LinearLayout advanced = column(); advanced.setVisibility(View.GONE);
        ui.button(form, s(R.string.mailpush_advanced), "mailpush.advanced", false, v -> {
            boolean expanded = advanced.getVisibility() != View.VISIBLE;
            advanced.setVisibility(expanded ? View.VISIBLE : View.GONE);
            ((Button) v).setText(s(expanded ? R.string.mailpush_hide_advanced : R.string.mailpush_advanced));
        });
        form.addView(advanced, new LinearLayout.LayoutParams(-1, -2));
        TextView vapidLabel = ui.text(advanced, s(R.string.mailpush_vapid_label), 14, ui.textColor());
        EditText vapid = new EditText(this); vapid.setId(View.generateViewId()); vapidLabel.setLabelFor(vapid.getId());
        vapid.setHint(R.string.mailpush_vapid_hint); vapid.setTag("mailpush.vapid"); ui.field(vapid);
        advanced.addView(vapid, new LinearLayout.LayoutParams(-1, -2));
        ui.text(advanced, s(R.string.mailpush_vapid_help), 13, ui.mutedColor());
        AlertDialog accountDialog = new AlertDialog.Builder(this).setTitle(R.string.mailpush_add_account).setView(formScroll)
                .setNegativeButton(R.string.mailpush_cancel, null).setPositiveButton(R.string.mailpush_continue, null).create();
        // Override the positive button after creation so a typo keeps the form
        // and its values on screen instead of dismissing and starting over.
        accountDialog.setOnShowListener(ignored -> accountDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            if (!authorized()) return;
            try {
                Set<String> allowed = new LinkedHashSet<>();
                for (String item : boxes.getText().toString().split(",")) {
                    String id = item.trim();
                    if (!id.matches("[A-Za-z0-9_-]{1,48}")) throw new IllegalArgumentException();
                    allowed.add(id);
                }
                if (allowed.isEmpty() || allowed.size() > 32) throw new IllegalArgumentException();
                String publicKey = vapid.getText().toString().trim();
                if (!publicKey.isEmpty() && !publicKey.matches("[A-Za-z0-9_-]{87}")) {
                    advanced.setVisibility(View.VISIBLE); vapid.setError(s(R.string.mailpush_vapid_invalid)); return;
                }
                MailPushIntegration.Account selected = accounts.get(account.getSelectedItemPosition());
                JSONObject profile = new JSONObject().put("instance", UUID.randomUUID().toString())
                        .put("account", selected.id).put("label", selected.label)
                        .put("mailboxes", new JSONArray(allowed)).put("paired", false)
                        .put("show_previews", false).put("vapid", publicKey).put("status", "Registering with push service");
                vault.put(profile); accountDialog.dismiss(); register(profile.getString("instance")); render();
            } catch (IllegalArgumentException invalid) { boxes.setError(s(R.string.mailpush_mailbox_invalid)); }
            catch (Exception failure) { fail(s(R.string.mailpush_create_failed)); }
        }));
        showPrivate(accountDialog);
    }

    private void register(String instance) {
        if (!authorized()) return;
        try {
            JSONObject profile = vault.get(instance); if (profile == null) return;
            if (UnifiedPush.getSavedDistributor(this) == null) { chooseDistributor(); return; }
            UnifiedPush.register(this, instance, "MailPush", profile.optString("vapid").isEmpty() ? null : profile.getString("vapid"));
            handler.postDelayed(this::render, 1500);
        } catch (Exception ignored) { fail(s(R.string.mailpush_registration_failed)); }
    }

    static JSONObject bundle(JSONObject profile) throws Exception {
        JSONObject subscription = profile.getJSONObject("subscription");
        return new JSONObject().put("format", "mailpush-receiver-v2").put("binding", profile.getString("instance"))
            .put("mailboxes", profile.getJSONArray("mailboxes")).put("endpoint", subscription.getString("endpoint"))
            .put("keys", subscription.getJSONObject("keys")).put("created_at", System.currentTimeMillis() / 1000);
    }

    private void exportRequest(String instance) {
        if (!authorized()) return;
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
        } catch (Exception ignored) { fail(s(R.string.mailpush_export_failed)); }
        finally { if (key != null) Arrays.fill(key, (byte) 0); }
        }
    }

    private void showKey(String instance) {
        if (!authorized()) return;
        try {
            JSONObject profile = vault.get(instance); if (profile == null || !profile.has("pending_key")) return;
            if (System.currentTimeMillis() / 1000 - profile.getLong("pending_at") > 86400) { fail(s(R.string.mailpush_pairing_expired)); return; }
            TextView key = new TextView(this); key.setPadding(dp(24), dp(16), dp(24), dp(16)); key.setTextSize(16); key.setTypeface(Typeface.MONOSPACE);
            key.setText(profile.getString("pending_key") + "\n\n" + s(R.string.mailpush_fingerprint) + "\n" + profile.getString("pending_fingerprint"));
            key.setTextColor(ui.textColor());
            key.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS); key.setTextIsSelectable(true);
            AlertDialog dialog = new AlertDialog.Builder(this).setTitle(R.string.mailpush_pairing_key)
                .setMessage(R.string.mailpush_pairing_key_help)
                .setView(key).setPositiveButton(R.string.mailpush_done, null).create();
            showPrivate(dialog);
        } catch (Exception ignored) { fail(s(R.string.mailpush_key_failed)); }
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
                Toast.makeText(this, R.string.mailpush_pairing_complete, Toast.LENGTH_LONG).show();
            }
        } catch (Exception ignored) { fail(s(R.string.mailpush_receipt_failed)); }
    }

    private void importReceipt(JSONObject profile, byte[] bytes) throws Exception {
        vault.update(profile.getString("instance"), current -> {
            JSONObject receipt = PairingCrypto.verifyReceipt(current, bytes, System.currentTimeMillis() / 1000);
            current.put("source", receipt.getString("source")).put("paired", true).put("status", "Paired · waiting for encrypted alerts");
            current.remove("pending_key"); current.remove("pending_request"); current.remove("pending_fingerprint"); current.remove("pending_at");
        });
    }

    private void remove(String instance) {
        if (!authorized()) return;
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
        } catch (Exception ignored) { fail(s(R.string.mailpush_remove_failed)); }
        }
    }

    private void fail(String message) {
        showPrivate(new AlertDialog.Builder(this).setTitle(R.string.mailpush_error_title).setMessage(message)
                .setPositiveButton(android.R.string.ok, null).create());
    }
}
