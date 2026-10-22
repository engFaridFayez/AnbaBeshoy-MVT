(() => {
    "use strict";

    const widget = document.getElementById("notificationWidget");
    if (widget) {
        const token = widget.querySelector('input[name="csrfmiddlewaretoken"]').value;
        const list = document.getElementById("nfyList");
        const badge = document.getElementById("nfyCount");
        const toast = document.getElementById("nfyToast");
        const enable = document.getElementById("nfyEnable");
        const disable = document.getElementById("nfyDisable");
        const status = document.getElementById("nfyPushStatus");
        const key = `notices-last-${widget.dataset.userId}`;
        let lastId = null;
        let timer = null;
        let busy = false;
        let stopped = false;
        let cfg = null;
        let registration = null;
        try {
            const saved = sessionStorage.getItem(key);
            if (saved !== null) lastId = Number(saved);
        } catch (_) {}

        async function api(url, payload) {
            const options = { credentials: "same-origin", cache: "no-store" };
            if (payload !== undefined) {
                options.method = "POST";
                options.headers = { "Content-Type": "application/json", "X-CSRFToken": token };
                options.body = JSON.stringify(payload);
            }
            const response = await fetch(url, options);
            if (response.status === 401) {
                stopped = true;
                throw new Error("انتهت جلسة الدخول. سجّل الدخول مرة أخرى.");
            }
            let data;
            try { data = await response.json(); } catch (_) { data = {}; }
            if (!response.ok) throw new Error(data.error || "تعذر الاتصال. حاول مرة أخرى.");
            return data;
        }

        function localTime(value) {
            try {
                return new Intl.DateTimeFormat("ar-EG", {
                    dateStyle: "short", timeStyle: "short"
                }).format(new Date(value));
            } catch (_) { return ""; }
        }

        function paint(items) {
            list.replaceChildren();
            if (!items.length) {
                const empty = document.createElement("p");
                empty.className = "nfy-muted";
                empty.textContent = "لا توجد إشعارات حتى الآن.";
                list.append(empty);
                return;
            }
            items.forEach((item) => {
                const link = document.createElement("a");
                link.className = `nfy-feed-item${item.read ? "" : " nfy-unread"}`;
                link.href = item.url;
                const title = document.createElement("strong");
                title.textContent = item.title;
                const body = document.createElement("span");
                body.textContent = item.body;
                const time = document.createElement("small");
                time.textContent = localTime(item.created_at);
                link.append(title, body, time);
                list.append(link);
            });
        }

        async function refreshFeed() {
            if (busy || stopped || document.hidden) return;
            busy = true;
            try {
                const data = await api(widget.dataset.feedUrl);
                badge.hidden = data.unread === 0;
                badge.textContent = data.unread > 99 ? "99+" : String(data.unread);
                widget.querySelector("summary").setAttribute(
                    "aria-label", `الإشعارات، ${data.unread} غير مقروء`
                );
                paint(data.items);
                if (lastId !== null && data.latest_id > lastId) {
                    const fresh = data.items.find((item) => item.id > lastId && !item.read);
                    if (fresh) {
                        toast.replaceChildren();
                        const link = document.createElement("a");
                        link.href = fresh.url;
                        link.textContent = `${fresh.title} — اضغط لعرض الإشعار`;
                        const close = document.createElement("button");
                        close.type = "button";
                        close.textContent = "×";
                        close.setAttribute("aria-label", "إخفاء التنبيه");
                        close.addEventListener("click", () => { toast.hidden = true; });
                        toast.append(link, close);
                        toast.hidden = false;
                        window.setTimeout(() => { toast.hidden = true; }, 8000);
                    }
                }
                lastId = data.latest_id;
                try { sessionStorage.setItem(key, String(lastId)); } catch (_) {}
            } catch (error) {
                if (stopped) status.textContent = error.message;
            } finally { busy = false; }
        }

        function schedule() {
            clearTimeout(timer);
            timer = setTimeout(async () => {
                await refreshFeed();
                if (!stopped) schedule();
            }, 10000);
        }

        widget.addEventListener("toggle", () => {
            if (widget.open) refreshFeed();
        });
        document.getElementById("nfyClose").addEventListener("click", () => {
            widget.open = false;
            widget.querySelector("summary").focus();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && widget.open) {
                widget.open = false;
                widget.querySelector("summary").focus();
            }
        });
        document.addEventListener("click", (event) => {
            if (widget.open && !widget.contains(event.target)) widget.open = false;
        });
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) refreshFeed();
        });
        window.addEventListener("pagehide", () => clearTimeout(timer));
        window.addEventListener("pageshow", () => { refreshFeed(); schedule(); });

        const isAppleMobile = /iPad|iPhone|iPod/.test(navigator.userAgent)
            || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
        const standalone = window.matchMedia("(display-mode: standalone)").matches
            || navigator.standalone === true;

        function toBytes(value) {
            const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
            return Uint8Array.from(raw, (c) => c.charCodeAt(0));
        }

        async function ensureRegistration() {
            const expected = new URL(cfg.worker_url, location.origin).href;
            const previous = await navigator.serviceWorker.getRegistration(cfg.scope);
            const existingScript = previous && (
                previous.active?.scriptURL || previous.waiting?.scriptURL || previous.installing?.scriptURL
            );
            if (existingScript && existingScript !== expected) {
                throw new Error("يوجد Service Worker آخر. يلزم دمج الإشعارات معه قبل التفعيل، دون حذفه.");
            }
            registration = await navigator.serviceWorker.register(cfg.worker_url, { scope: cfg.scope });
            if (!registration.active) {
                await new Promise((resolve, reject) => {
                    const worker = registration.installing || registration.waiting;
                    if (!worker) return reject(new Error("تعذر تشغيل خدمة الإشعارات."));
                    const timeout = setTimeout(() => reject(new Error("تعذر تشغيل خدمة الإشعارات. أعد المحاولة.")), 15000);
                    const changed = () => {
                        if (worker.state === "activated") {
                            clearTimeout(timeout);
                            resolve();
                        } else if (worker.state === "redundant") {
                            clearTimeout(timeout);
                            reject(new Error("تعذر تشغيل خدمة الإشعارات."));
                        }
                    };
                    worker.addEventListener("statechange", changed);
                    changed();
                });
            }
            return registration;
        }

        async function bind(sub) {
            await api(widget.dataset.subscribeUrl, sub.toJSON());
            enable.hidden = true;
            disable.hidden = false;
            status.textContent = "تنبيهات الموبايل مفعّلة لهذا الجهاز.";
        }

        enable.addEventListener("click", async () => {
            if (!cfg || !cfg.enabled) return;
            enable.disabled = true;
            try {
                // Request permission directly in response to the user's click.
                const permission = await Notification.requestPermission();
                if (permission !== "granted") {
                    throw new Error("لم يتم السماح بالإشعارات. يمكنك تغيير الإذن من إعدادات الموقع.");
                }
                const reg = await ensureRegistration();
                let sub = await reg.pushManager.getSubscription();
                if (!sub) {
                    sub = await reg.pushManager.subscribe({
                        userVisibleOnly: true, applicationServerKey: toBytes(cfg.public_key),
                    });
                }
                await bind(sub);
            } catch (error) {
                status.textContent = error.message;
            } finally { enable.disabled = false; }
        });

        disable.addEventListener("click", async () => {
            disable.disabled = true;
            try {
                const reg = registration || await navigator.serviceWorker.getRegistration("/");
                const sub = reg ? await reg.pushManager.getSubscription() : null;
                if (sub) {
                    await api(widget.dataset.unsubscribeUrl, { endpoint: sub.endpoint });
                    await sub.unsubscribe();
                }
                disable.hidden = true;
                enable.hidden = false;
                status.textContent = "تم إيقاف تنبيهات الجهاز. إشعارات الحساب محفوظة داخل التطبيق.";
            } catch (error) { status.textContent = error.message; }
            finally { disable.disabled = false; }
        });

        async function initPush() {
            enable.disabled = true;
            try {
                if (!window.isSecureContext) {
                    status.textContent = "تنبيهات الهاتف تحتاج رابط HTTPS. الإشعارات الداخلية تعمل.";
                    return;
                }
                if (isAppleMobile && !standalone) {
                    status.textContent = "على iPhone: أضف الموقع للشاشة الرئيسية ثم افتحه منها لتفعيل الإشعارات.";
                    return;
                }
                if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
                    status.textContent = "هذا المتصفح لا يدعم Push. ستجد رسائلك داخل التطبيق.";
                    return;
                }
                cfg = await api(widget.dataset.configUrl);
                if (!cfg.enabled) {
                    status.textContent = "الإشعارات الداخلية تعمل. تفعيل تنبيهات الهاتف ينتظر إعداد السيرفر.";
                    return;
                }
                enable.disabled = false;
                if (Notification.permission === "denied") {
                    status.textContent = "الإذن محظور. اسمح بالإشعارات من إعدادات الموقع أولًا.";
                    return;
                }
                if (Notification.permission === "granted") {
                    const existing = await navigator.serviceWorker.getRegistration("/");
                    if (existing) {
                        const actual = existing.active?.scriptURL;
                        const expected = new URL(cfg.worker_url, location.origin).href;
                        if (actual === expected) {
                            registration = existing;
                            const sub = await existing.pushManager.getSubscription();
                            if (sub) await bind(sub);
                        }
                    }
                }
            } catch (error) { status.textContent = error.message; }
        }
        refreshFeed();
        schedule();
        initPush();
    }

    // Recipient selectors on the manager page.
    document.querySelectorAll(".nfy-audience").forEach((box) => {
        const people = box.querySelector(".nfy-people");
        const radios = Array.from(box.querySelectorAll('input[type="radio"]'));
        const labels = Array.from(box.querySelectorAll(".nfy-user-list label"));
        const checks = Array.from(box.querySelectorAll('.nfy-user-list input[type="checkbox"]'));
        const count = box.querySelector(".nfy-selected-count");
        const search = box.querySelector(".nfy-search");
        const update = () => {
            people.hidden = radios.find((r) => r.checked)?.value !== "selected";
            count.textContent = `${checks.filter((c) => c.checked).length} مستخدم محدد`;
        };
        radios.forEach((radio) => radio.addEventListener("change", update));
        checks.forEach((checkbox) => checkbox.addEventListener("change", update));
        search.addEventListener("input", () => {
            const query = search.value.trim().toLocaleLowerCase();
            labels.forEach((label) => {
                label.parentElement.hidden = !label.textContent.toLocaleLowerCase().includes(query);
            });
        });
        box.querySelector(".nfy-select-visible").addEventListener("click", () => {
            labels.forEach((label) => {
                if (!label.parentElement.hidden) label.querySelector("input").checked = true;
            });
            update();
        });
        box.querySelector(".nfy-clear").addEventListener("click", () => {
            checks.forEach((checkbox) => { checkbox.checked = false; });
            update();
        });
        update();
    });
})();
