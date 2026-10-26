package app.mailpush.companion;

import org.json.JSONObject;

/**
 * Presentation policy only: validation/decryption and account checks happen
 * before this is called. No message content is persisted by this class.
 */
final class NotificationPreview {
    static final String APP_TITLE = "Proton Mail";
    static final String NEW_MAIL = "You have new mail";
    static final String TEST = "Encrypted test received";

    static final class Content {
        final String title;
        final String text;
        final String accountLabel;
        final boolean preview;

        private Content(String title, String text, String accountLabel, boolean preview) {
            this.title = title;
            this.text = text;
            this.accountLabel = accountLabel;
            this.preview = preview;
        }
    }

    private NotificationPreview() { }

    static boolean enabled(JSONObject profile) {
        // Existing installations and malformed/non-boolean settings stay private.
        return profile != null && Boolean.TRUE.equals(profile.opt("show_previews"));
    }

    static Content generic(JSONObject event) {
        return new Content(APP_TITLE, "test".equals(event.optString("type")) ? TEST : NEW_MAIL, "", false);
    }

    static Content content(JSONObject event, JSONObject profile) {
        if (!enabled(profile) || !"new_mail".equals(event.optString("type"))) return generic(event);
        String sender = clean(event.opt("sender"), 160);
        String subject = clean(event.opt("subject"), 240);
        if (sender.isEmpty() && subject.isEmpty()) return generic(event);
        return new Content(sender.isEmpty() ? APP_TITLE : sender,
            subject.isEmpty() ? "(No subject)" : subject,
            clean(profile.opt("label"), 160), true);
    }

    private static String clean(Object value, int limit) {
        if (!(value instanceof String)) return "";
        // Framework notification builders receive plain strings, never HTML or
        // Spanned text. Strip line/bidi controls and bound even local labels.
        String text = EventPolicy.safeText((String) value).trim();
        if (text.codePoints().allMatch(c -> Character.isWhitespace(c) || Character.isSpaceChar(c))) return "";
        return text.codePointCount(0, text.length()) <= limit
            ? text : text.substring(0, text.offsetByCodePoints(0, limit));
    }
}
