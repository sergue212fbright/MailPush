package app.mailpush.companion;

import android.content.ContentValues;
import android.content.Context;
import android.database.DatabaseUtils;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class Ledger extends SQLiteOpenHelper {
    Ledger(Context context) { super(context, "mailpush-dedup.sqlite", null, 1); }
    @Override public void onCreate(SQLiteDatabase db) { db.execSQL("CREATE TABLE seen(id TEXT PRIMARY KEY,expires INTEGER NOT NULL)"); }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("Unsupported ledger schema"); }

    boolean claim(String instance, String eventId, long expires, long now) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest((instance + ":" + eventId).getBytes(StandardCharsets.UTF_8));
        String id = PairingCrypto.b64(hash);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("seen", "expires <= ?", new String[]{Long.toString(now)});
            if (DatabaseUtils.queryNumEntries(db, "seen") >= 50000) return false;
            ContentValues row = new ContentValues(); row.put("id", id); row.put("expires", expires);
            boolean added = db.insertWithOnConflict("seen", null, row, SQLiteDatabase.CONFLICT_IGNORE) != -1;
            db.setTransactionSuccessful();
            return added;
        } finally { db.endTransaction(); }
    }
}
