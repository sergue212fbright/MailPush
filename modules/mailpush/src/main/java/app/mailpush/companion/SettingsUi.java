package app.mailpush.companion;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Small framework-view presentation layer owned by the push module.
 *
 * The palette deliberately resembles the mail settings, but references only our
 * own resources. Changes to Proton's theme classes or resource names therefore
 * cannot break this screen. There is no account, key or transport logic here.
 */
final class SettingsUi {
    private final Activity activity;

    SettingsUi(Activity activity) { this.activity = activity; }

    int dp(int value) {
        return Math.round(activity.getResources().getDisplayMetrics().density * value);
    }

    private int color(int resource) { return activity.getColor(resource); }
    int textColor() { return color(R.color.mailpush_text); }
    int mutedColor() { return color(R.color.mailpush_muted); }
    int accentColor() { return color(R.color.mailpush_accent); }
    int backgroundColor() { return color(R.color.mailpush_background); }
    int dangerColor() { return color(R.color.mailpush_danger); }

    LinearLayout column() {
        LinearLayout view = new LinearLayout(activity);
        view.setOrientation(LinearLayout.VERTICAL);
        return view;
    }

    LinearLayout card(LinearLayout parent) {
        LinearLayout view = column();
        view.setPadding(dp(18), dp(14), dp(18), dp(14));
        view.setBackground(shape(color(R.color.mailpush_surface), 20, false));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(12);
        parent.addView(view, params);
        return view;
    }

    TextView text(LinearLayout parent, String value, int size, int textColor) {
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(textColor);
        view.setPadding(0, dp(3), 0, dp(5));
        view.setBreakStrategy(android.graphics.text.LineBreaker.BREAK_STRATEGY_HIGH_QUALITY);
        parent.addView(view, new LinearLayout.LayoutParams(-1, -2));
        return view;
    }

    TextView section(LinearLayout parent, String value) {
        TextView view = text(parent, value, 14, mutedColor());
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setPadding(dp(4), dp(14), 0, dp(10));
        view.setAccessibilityHeading(true);
        return view;
    }

    TextView badge(LinearLayout parent, String value) {
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(13);
        view.setTextColor(accentColor());
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setPadding(dp(10), dp(5), dp(10), dp(5));
        view.setBackground(shape(color(R.color.mailpush_accent_soft), 12, false));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-2, -2);
        params.topMargin = dp(5);
        params.bottomMargin = dp(8);
        parent.addView(view, params);
        return view;
    }

    Button button(LinearLayout parent, String label, String tag, boolean primary,
                  View.OnClickListener action) {
        Button view = new Button(activity);
        view.setText(label);
        view.setTag(tag);
        view.setTextSize(15);
        view.setAllCaps(false);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setMinHeight(dp(48));
        view.setMinimumHeight(dp(48));
        view.setPadding(dp(16), dp(12), dp(16), dp(12));
        // No fixed height: larger accessibility fonts can wrap naturally.
        view.setTextColor(new ColorStateList(
            new int[][] {new int[] {-android.R.attr.state_enabled}, new int[] {}},
            new int[] {color(R.color.mailpush_disabled_text),
                primary ? color(R.color.mailpush_on_accent) : accentColor()}));
        StateListDrawable fills = new StateListDrawable();
        fills.addState(new int[] {-android.R.attr.state_enabled},
            shape(color(R.color.mailpush_disabled), 14, false));
        fills.addState(new int[] {}, shape(primary ? accentColor() :
            color(R.color.mailpush_surface), 14, !primary));
        view.setBackground(new RippleDrawable(
            ColorStateList.valueOf(color(R.color.mailpush_ripple)), fills, null));
        // Some platform Button styles keep a tint even after setBackground().
        // Our module palette owns the drawable; an inherited tint would turn
        // every action back into the same system-grey button.
        view.setBackgroundTintList(null);
        view.setStateListAnimator(null);
        view.setOnClickListener(action);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(6);
        params.bottomMargin = dp(4);
        parent.addView(view, params);
        return view;
    }

    /** Quiet informational/maintenance links keep the primary action distinct. */
    Button textAction(LinearLayout parent, String label, String tag, View.OnClickListener action) {
        Button view = button(parent, label, tag, false, action);
        view.setTypeface(Typeface.DEFAULT, Typeface.NORMAL);
        view.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        view.setPadding(0, dp(10), 0, dp(10));
        view.setBackground(new RippleDrawable(ColorStateList.valueOf(color(R.color.mailpush_ripple)),
                shape(Color.TRANSPARENT, 10, false), null));
        LinearLayout.LayoutParams params = (LinearLayout.LayoutParams) view.getLayoutParams();
        params.topMargin = 0; params.bottomMargin = 0;
        return view;
    }

    void divider(LinearLayout parent) {
        View view = new View(activity);
        view.setBackgroundColor(color(R.color.mailpush_border));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(1));
        params.topMargin = dp(12);
        params.bottomMargin = dp(10);
        parent.addView(view, params);
    }

    void gap(LinearLayout parent, int heightDp) {
        View view = new View(activity);
        view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        parent.addView(view, new LinearLayout.LayoutParams(1, dp(heightDp)));
    }

    void field(EditText view) {
        view.setTextColor(textColor());
        view.setHintTextColor(mutedColor());
        view.setTextSize(16);
        view.setSingleLine(true);
        view.setMinHeight(dp(48));
        view.setPadding(dp(4), dp(10), dp(4), dp(10));
        view.setBackgroundTintList(ColorStateList.valueOf(accentColor()));
    }

    private GradientDrawable shape(int fill, int radiusDp, boolean border) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radiusDp));
        if (border) drawable.setStroke(dp(1), color(R.color.mailpush_border));
        return drawable;
    }
}
