package app.mailpush.companion;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

/** Consent and sanitization regressions independent of Android rendering. */
public class NotificationPreviewTest {
    private JSONObject event() throws Exception {
        return new JSONObject().put("type", "new_mail")
            .put("sender", "Synthetic sender <sender@example.invalid>")
            .put("subject", "Synthetic private subject");
    }

    private JSONObject profile() throws Exception {
        return new JSONObject().put("label", "Private account label");
    }

    private void generic(NotificationPreview.Content content, String text) {
        assertFalse(content.preview);
        assertEquals("Proton Mail", content.title);
        assertEquals(text, content.text);
        assertEquals("", content.accountLabel);
    }

    @Test public void existingProfilesDefaultToGenericEvenWhenPayloadHasPreview() throws Exception {
        generic(NotificationPreview.content(event(), profile()), "You have new mail");
        generic(NotificationPreview.content(event(), null), "You have new mail");
    }

    @Test public void onlyExplicitBooleanOptInEnablesPreview() throws Exception {
        for (Object value : new Object[] { false, "true", 1, JSONObject.NULL }) {
            generic(NotificationPreview.content(event(), profile().put("show_previews", value)), "You have new mail");
        }
    }

    @Test public void optedInMailShowsSenderSubjectAndLocalAccountLabel() throws Exception {
        NotificationPreview.Content content = NotificationPreview.content(event(), profile().put("show_previews", true));
        assertTrue(content.preview);
        assertEquals("Synthetic sender <sender@example.invalid>", content.title);
        assertEquals("Synthetic private subject", content.text);
        assertEquals("Private account label", content.accountLabel);
    }

    @Test public void testEventsRemainGenericEvenWithPreviewFieldsAndConsent() throws Exception {
        generic(NotificationPreview.content(event().put("type", "test"), profile().put("show_previews", true)), "Encrypted test received");
    }

    @Test public void subjectOnlyHasSafeAppTitle() throws Exception {
        JSONObject event = event(); event.remove("sender");
        NotificationPreview.Content content = NotificationPreview.content(event, profile().put("show_previews", true));
        assertTrue(content.preview);
        assertEquals("Proton Mail", content.title);
        assertEquals("Synthetic private subject", content.text);
    }

    @Test public void senderOnlyHasNoSubjectFallback() throws Exception {
        JSONObject event = event(); event.remove("subject");
        NotificationPreview.Content content = NotificationPreview.content(event, profile().put("show_previews", true));
        assertTrue(content.preview);
        assertEquals("(No subject)", content.text);
    }

    @Test public void controlsBidiAndUnicodeLineSeparatorsCannotInjectLines() throws Exception {
        JSONObject event = event().put("sender", "Alice\r\n\u202e\u2028Bob")
            .put("subject", "Hello\t\u2066\u2029world");
        JSONObject profile = profile().put("show_previews", true).put("label", "Work\n\u2028account");
        NotificationPreview.Content content = NotificationPreview.content(event, profile);
        assertEquals("AliceBob", content.title);
        assertEquals("Helloworld", content.text);
        assertEquals("Workaccount", content.accountLabel);
    }

    @Test public void emptySanitizedMetadataFallsBackWithoutLeakingAccountLabel() throws Exception {
        JSONObject event = event().put("sender", "\n\u202e\u2028").put("subject", "\u2000\u00a0");
        generic(NotificationPreview.content(event, profile().put("show_previews", true)), "You have new mail");
    }

    @Test public void markupIsKeptAsLiteralPlainText() throws Exception {
        NotificationPreview.Content content = NotificationPreview.content(
            event().put("subject", "<b>literal</b> & ordinary text"), profile().put("show_previews", true));
        assertEquals("<b>literal</b> & ordinary text", content.text);
    }

    @Test public void localLabelAndPreviewBoundsDoNotSplitSupplementaryCharacters() throws Exception {
        String rocket = "\ud83d\ude80";
        NotificationPreview.Content content = NotificationPreview.content(
            event().put("sender", rocket.repeat(170)).put("subject", rocket.repeat(250)),
            profile().put("show_previews", true).put("label", rocket.repeat(200)));
        assertEquals(rocket.repeat(160), content.title);
        assertEquals(rocket.repeat(240), content.text);
        assertEquals(rocket.repeat(160), content.accountLabel);
    }

    @Test public void unexpectedMetadataTypesAreNotStringifiedIntoPreview() throws Exception {
        JSONObject event = event().put("sender", new JSONObject().put("private", "data")).put("subject", 123);
        generic(NotificationPreview.content(event, profile().put("show_previews", true)), "You have new mail");
    }
}
