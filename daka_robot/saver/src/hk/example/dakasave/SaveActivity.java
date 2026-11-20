package hk.example.dakasave;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.InputStream;
import java.io.OutputStream;

/** Writes a shared DAKA export into Downloads. No network, no account. */
public class SaveActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        Uri source = intent == null ? null : intent.getParcelableExtra(Intent.EXTRA_STREAM);
        if (source != null) {
            copy(source);
        }
        finish();
    }

    private void copy(Uri source) {
        try {
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, "daka_export_" + System.currentTimeMillis() + ".csv");
            values.put(MediaStore.Downloads.MIME_TYPE, "text/csv");
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
            Uri dest = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (dest == null) {
                return;
            }
            InputStream in = getContentResolver().openInputStream(source);
            OutputStream out = getContentResolver().openOutputStream(dest);
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            in.close();
            out.close();
        } catch (Exception error) {
            error.printStackTrace();
        }
    }
}
