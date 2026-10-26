package app.mailpush.companion;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Independent of Android so hostile input and replay policy can be tested on a JVM. */
final class EventPolicy {
    static JSONObject validate(byte[] bytes, boolean decrypted, String instance, JSONObject profile, long now) throws Exception {
        if (!decrypted || bytes.length > 4096 || profile == null || !profile.optBoolean("paired")) throw new SecurityException("Unpaired or unencrypted");
        String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        JSONObject event = new JSONObject(text);
        if (strictLong(event, "v") != 2 || !instance.equals(profile.getString("instance")) || !instance.equals(event.getString("binding"))) throw new SecurityException("Binding mismatch");
        if (!profile.getString("source").equals(event.getString("source"))) throw new SecurityException("Source mismatch");
        uuid(event.getString("event_id")); uuid(event.getString("source")); uuid(instance);
        String type = event.getString("type"), mailbox = event.getString("mailbox");
        if (!type.equals("new_mail") && !type.equals("test")) throw new SecurityException("Unsupported event");
        boolean known = false;
        JSONArray boxes = profile.getJSONArray("mailboxes");
        for (int i = 0; i < boxes.length(); i++) known |= boxes.getString(i).equals(mailbox);
        if (!type.equals("test") && !known) throw new SecurityException("Unapproved mailbox");
        long created = strictLong(event, "created_at"), expires = strictLong(event, "expires_at");
        if (created > now + 300 || created < now - 86700 || expires <= now || expires - created < 60 || expires - created > 86400) throw new SecurityException("Expired or invalid time");
        if (event.has("sender") && (!(event.get("sender") instanceof String) || event.getString("sender").codePointCount(0, event.getString("sender").length()) > 160)) throw new SecurityException("Sender too long");
        if (event.has("subject") && (!(event.get("subject") instanceof String) || event.getString("subject").codePointCount(0, event.getString("subject").length()) > 240)) throw new SecurityException("Subject too long");
        return event;
    }

    private static long strictLong(JSONObject obj, String field) throws Exception {
        Object value = obj.get(field);
        if (!(value instanceof Integer) && !(value instanceof Long)) throw new SecurityException("Integer required");
        return ((Number) value).longValue();
    }

    static void uuid(String value) {
        if (!UUID.fromString(value).toString().equals(value)) throw new SecurityException("Invalid UUID");
    }

    static String safeText(String text) {
        StringBuilder out = new StringBuilder();
        text.codePoints().filter(c -> !Character.isISOControl(c)
            && Character.getType(c) != Character.FORMAT
            && Character.getType(c) != Character.LINE_SEPARATOR
            && Character.getType(c) != Character.PARAGRAPH_SEPARATOR).forEach(out::appendCodePoint);
        return out.toString();
    }
}
