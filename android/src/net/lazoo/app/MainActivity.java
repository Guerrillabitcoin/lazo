package net.lazoo.app;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.InputStream;
import java.net.InetAddress;

/**
 * LaZoo para Android: al abrir sale el escáner de QR (assets/escaner.html, con jsQR, sin
 * servicios de Google). Al leer el QR del PC carga la web de LaZoo del anfitrión en este
 * mismo WebView, así el cliente firmado/sellado es el de siempre. Solo hosts de red local.
 */
public class MainActivity extends Activity {
    static final String ASSETS = "https://appassets.androidplatform.net/assets/";
    static final String SCANNER = ASSETS + "escaner.html";
    static final int REQ_CAMERA = 1, REQ_FILE = 2, REQ_NOTIFY = 3;
    static final String CHANNEL = "lazoo-aprobacion";
    static final int NOTE_WAIT = 54;

    WebView web;
    WifiManager.WifiLock wifiLock;
    PermissionRequest pendingPermission;
    ValueCallback<Uri[]> pendingFiles;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        web.addJavascriptInterface(new Bridge(), "LaZooApp");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        if (state != null) web.restoreState(state);
        else web.loadUrl(SCANNER);
    }

    // 0.50: Wi-Fi despierto y en baja latencia solo mientras la app está delante.
    @SuppressWarnings("deprecation")
    void holdWifi(boolean on) {
        try {
            if (on) {
                if (wifiLock == null) {
                    WifiManager wm = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
                    if (wm == null) return;
                    int mode = Build.VERSION.SDK_INT >= 29 ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
                    wifiLock = wm.createWifiLock(mode, "LaZoo:raton");
                    wifiLock.setReferenceCounted(false);
                }
                if (!wifiLock.isHeld()) wifiLock.acquire();
            } else if (wifiLock != null && wifiLock.isHeld()) {
                wifiLock.release();
            }
        } catch (Exception e) {
            // sin bloqueo: la app sigue igual
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        holdWifi(true);
    }

    @Override
    protected void onPause() {
        holdWifi(false);
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        holdWifi(false);
        clearWaitNote();
        super.onDestroy();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    // 0.54: aviso en la barra de notificaciones mientras el PC no acepta este móvil.
    // Canal nativo de Android, sin servicios de Google (vale en GrapheneOS).
    String noteTitle, noteText;

    void showWaitNote(String title, String text) {
        noteTitle = title;
        noteText = text;
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm == null) return;
            if (Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFY);
                return; // el aviso de arriba de la pantalla sigue saliendo igual
            }
            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = new NotificationChannel(CHANNEL, "Aprobación en el PC", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("Avisa cuando hay que aceptar este móvil en el PC");
                nm.createNotificationChannel(ch);
                b = new Notification.Builder(this, CHANNEL);
            } else {
                b = new Notification.Builder(this).setPriority(Notification.PRIORITY_HIGH);
            }
            Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            b.setSmallIcon(R.drawable.ic_notif).setContentTitle(title).setContentText(text)
                    .setStyle(new Notification.BigTextStyle().bigText(text))
                    .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(pi).setCategory(Notification.CATEGORY_STATUS);
            nm.notify(NOTE_WAIT, b.build());
        } catch (Exception e) {
            // sin aviso del sistema: queda el de la pantalla
        }
    }

    void clearWaitNote() {
        noteTitle = null;
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null) nm.cancel(NOTE_WAIT);
        } catch (Exception e) {
            // nada
        }
    }

    SharedPreferences prefs() { return getSharedPreferences("lazoo", MODE_PRIVATE); }

    /** true si el host es de red local o privada (no internet). */
    static boolean privateHost(String host) {
        if (host == null || host.isEmpty()) return false;
        host = host.replace("[", "").replace("]", "");
        if (!host.matches("[0-9a-fA-F:.%]+")) return false; // solo IP literal, sin DNS
        try {
            InetAddress a = InetAddress.getByName(host);
            if (a.isSiteLocalAddress() || a.isLinkLocalAddress() || a.isLoopbackAddress()) return true;
            byte[] b = a.getAddress();
            return b.length == 16 && (b[0] & 0xfe) == 0xfc; // IPv6 ULA fc00::/7
        } catch (Exception e) {
            return false;
        }
    }

    static boolean allowedUrl(String url) {
        try {
            Uri u = Uri.parse(url);
            String scheme = u.getScheme();
            return ("http".equals(scheme) || "https".equals(scheme)) && privateHost(u.getHost());
        } catch (Exception e) {
            return false;
        }
    }

    void openHost(String url) {
        if (!allowedUrl(url)) return;
        int cut = url.indexOf('#');  // 0.56: sin la ficha del QR (#p=...), que caduca al usarla
        prefs().edit().putString("last", cut >= 0 ? url.substring(0, cut) : url).apply();
        web.loadUrl(url);
    }

    void rescan() { web.loadUrl(SCANNER); }

    class Bridge {
        @JavascriptInterface
        public boolean open(final String url) {
            if (!allowedUrl(url)) return false;
            runOnUiThread(() -> openHost(url));
            return true;
        }

        @JavascriptInterface
        public String version() {
            try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionName; }
            catch (Exception e) { return ""; }
        }

        @JavascriptInterface
        public String last() { return prefs().getString("last", ""); }

        @JavascriptInterface
        public void scan() { runOnUiThread(MainActivity.this::rescan); }

        @JavascriptInterface
        public void waitNote(final String title, final String text) {
            final String t = title == null ? "LaZoo" : title.substring(0, Math.min(80, title.length()));
            final String x = text == null ? "" : text.substring(0, Math.min(240, text.length()));
            runOnUiThread(() -> showWaitNote(t, x));
        }

        @JavascriptInterface
        public void clearNote() { runOnUiThread(MainActivity.this::clearWaitNote); }
    }

    class Client extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!"appassets.androidplatform.net".equals(u.getHost())) return null;
            String path = u.getPath();
            if (path == null || !path.startsWith("/assets/") || path.contains("..")) return null;
            String name = path.substring(8);
            String mime = name.endsWith(".html") ? "text/html" : name.endsWith(".js") ? "text/javascript"
                    : name.endsWith(".png") ? "image/png" : "text/plain";
            try {
                InputStream in = getAssets().open(name);
                return new WebResourceResponse(mime, "utf-8", in);
            } catch (Exception e) {
                return new WebResourceResponse("text/plain", "utf-8", 404, "No está", null, null);
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            String url = req.getUrl().toString();
            if (url.startsWith(ASSETS)) return false;
            if (allowedUrl(url)) return false;
            return true; // nada fuera de la red local
        }
    }

    class Chrome extends WebChromeClient {
        @Override
        public void onPermissionRequest(final PermissionRequest request) {
            boolean fromApp = request.getOrigin() != null
                    && "appassets.androidplatform.net".equals(request.getOrigin().getHost());
            boolean camera = false;
            for (String r : request.getResources())
                if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r)) camera = true;
            if (!fromApp || !camera) { request.deny(); return; }
            if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            } else {
                pendingPermission = request;
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
            }
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (pendingFiles != null) pendingFiles.onReceiveValue(null);
            pendingFiles = callback;
            Intent i = new Intent(Intent.ACTION_GET_CONTENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
            try {
                startActivityForResult(Intent.createChooser(i, "Elegir archivos"), REQ_FILE);
            } catch (Exception e) {
                pendingFiles = null;
                return false;
            }
            return true;
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code == REQ_NOTIFY) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED && noteTitle != null)
                showWaitNote(noteTitle, noteText);
            return;
        }
        if (code != REQ_CAMERA || pendingPermission == null) return;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
            pendingPermission.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        else
            pendingPermission.deny();
        pendingPermission = null;
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        if (code != REQ_FILE || pendingFiles == null) return;
        Uri[] out = null;
        if (result == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                int n = data.getClipData().getItemCount();
                out = new Uri[n];
                for (int k = 0; k < n; k++) out[k] = data.getClipData().getItemAt(k).getUri();
            } else if (data.getData() != null) {
                out = new Uri[]{data.getData()};
            }
        }
        pendingFiles.onReceiveValue(out);
        pendingFiles = null;
    }

    @Override
    public void onBackPressed() {
        String url = web.getUrl();
        if (url != null && url.startsWith(ASSETS)) { super.onBackPressed(); return; }
        rescan(); // desde el PC, «atrás» vuelve al escáner
    }
}
