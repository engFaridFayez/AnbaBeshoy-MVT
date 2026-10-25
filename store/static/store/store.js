/* UI duplicate-click guard only; not a database idempotency mechanism. */
(() => {
    "use strict";
    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches("[data-store-submit]")) return;
        if (event.defaultPrevented) return;
        if (form.dataset.storeBusy === "1") {
            event.preventDefault();
            return;
        }
        form.dataset.storeBusy = "1";
        // Let all validation/confirmation listeners run first.
        queueMicrotask(() => {
            if (event.defaultPrevented) {
                delete form.dataset.storeBusy;
                return;
            }
            form.setAttribute("aria-busy", "true");
            form.querySelectorAll('button[type="submit"]').forEach((button) => {
                button.disabled = true;
            });
        });
    });
    window.addEventListener("pageshow", () => {
        document.querySelectorAll("form[data-store-submit]").forEach((form) => {
            delete form.dataset.storeBusy;
            form.removeAttribute("aria-busy");
            form.querySelectorAll('button[type="submit"]').forEach((button) => {
                button.disabled = false;
            });
        });
    });
})();
