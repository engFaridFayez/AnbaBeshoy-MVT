/* No offline cache: authenticated pages and personal notifications are never cached. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function safePath(value, fallback) {
    try {
        const url = new URL(value || fallback, self.location.origin);
        return url.origin === self.location.origin ? url.href : new URL(fallback, self.location.origin).href;
    } catch (_) { return new URL(fallback, self.location.origin).href; }
}

self.addEventListener("push", (event) => {
    let payload = {};
    try { payload = event.data ? event.data.json() : {}; } catch (_) {}
    const title = String(payload.title || "طلبات الدير").slice(0, 120);
    event.waitUntil(self.registration.showNotification(title, {
        body: String(payload.body || "يوجد إشعار جديد في حسابك.").slice(0, 600),
        icon: safePath(payload.icon, "/static/notifications/icon-192.png"),
        badge: safePath(payload.badge, "/static/notifications/badge.png"),
        lang: "ar",
        dir: "rtl",
        tag: String(payload.tag || "monastery-update"),
        data: { url: safePath(payload.url, "/notifications/") },
    }));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = safePath(event.notification.data?.url, "/notifications/");
    // Do not navigate an already-open ordering form: it may contain unsaved quantities.
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
            const exact = windows.find((client) => client.url === target);
            return exact ? exact.focus() : self.clients.openWindow(target);
        })
    );
});
