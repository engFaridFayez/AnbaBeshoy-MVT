(() => {
    "use strict";

    // =====================================
    // التنبيه إلى التعديلات غير المحفوظة
    // =====================================

    const dirtyForms = new Set();
    let leavingAfterSubmit = false;

    document.querySelectorAll("[data-track-changes]").forEach((form) => {
        const getSignature = () => {
            const values = Array.from(new FormData(form).entries())
                .filter(([name]) => name !== "csrfmiddlewaretoken");

            return JSON.stringify(values);
        };

        const initialSignature = getSignature();

        const noteId = form.dataset.changeNote;
        const note = noteId ? document.getElementById(noteId) : null;

        const updateDirtyState = () => {
            const changed = getSignature() !== initialSignature;

            if (changed) {
                dirtyForms.add(form);
            } else {
                dirtyForms.delete(form);
            }

            if (note) {
                note.hidden = !changed;
            }
        };

        form.addEventListener("input", updateDirtyState);
        form.addEventListener("change", updateDirtyState);
    });

    window.addEventListener("beforeunload", (event) => {
        if (dirtyForms.size > 0 && !leavingAfterSubmit) {
            event.preventDefault();
            event.returnValue = "";
        }
    });

    document.addEventListener("submit", (event) => {
        if (event.defaultPrevented) {
            return;
        }

        const form = event.target;

        const anotherFormHasChanges = Array.from(dirtyForms)
            .some((dirtyForm) => dirtyForm !== form);

        if (anotherFormHasChanges) {
            event.preventDefault();

            window.alert(
                "لديك اختيارات لم تُحفظ. اضغط زر الحفظ أولًا، ثم نفّذ العملية الأخرى."
            );

            return;
        }

        const confirmation = form.dataset.confirm;

        if (confirmation && !window.confirm(confirmation)) {
            event.preventDefault();
            return;
        }

        leavingAfterSubmit = true;
        dirtyForms.delete(form);
    });

    // =====================================
    // أزرار زيادة وتقليل الكمية
    // =====================================

    document.querySelectorAll("[data-step]").forEach((button) => {
        button.addEventListener("click", () => {
            const stepper = button.closest(".ui-stepper");
            const input = stepper.querySelector("[data-quantity]");

            const step = Number(button.dataset.step);
            const minimum = Number(input.min);
            const maximum = Number(input.max);

            const current = Number.parseInt(input.value, 10) || 0;

            input.value = String(
                Math.min(
                    maximum,
                    Math.max(minimum, current + step)
                )
            );

            input.dispatchEvent(
                new Event("input", { bubbles: true })
            );
        });
    });

    // =====================================
    // ملخص اختيارات الراهب
    // =====================================

    const quantityInputs = Array.from(
        document.querySelectorAll("[data-quantity]")
    );

    const summary = document.getElementById("orderSummaryText");
    const saveOrderButton = document.getElementById("saveOrderButton");

    const updateOrderSummary = () => {
        const selectedItems = [];

        let allValid = true;

        quantityInputs.forEach((input) => {
            const quantity = Number(input.value);

            if (!input.validity.valid || !Number.isInteger(quantity)) {
                allValid = false;
                return;
            }

            if (quantity > 0) {
                selectedItems.push(
                    `${input.dataset.name} × ${quantity}`
                );
            }
        });

        if (summary) {
            summary.textContent = selectedItems.length > 0
                ? selectedItems.join("، ")
                : "لم تختَر أصنافًا بعد.";
        }

        if (saveOrderButton) {
            saveOrderButton.disabled = (
                !allValid || selectedItems.length === 0
            );
        }
    };

    quantityInputs.forEach((input) => {
        input.addEventListener("input", updateOrderSummary);
    });

    updateOrderSummary();

    // =====================================
    // عدد الأصناف المختارة لدى المسؤول
    // =====================================

    const availabilityForm = document.getElementById("availabilityForm");
    const availableCount = document.getElementById("availableCount");

    if (availabilityForm && availableCount) {
        const updateAvailableCount = () => {
            availableCount.textContent = String(
                availabilityForm.querySelectorAll(
                    'input[name="item_ids"]:checked'
                ).length
            );
        };

        availabilityForm.addEventListener(
            "change",
            updateAvailableCount
        );

        updateAvailableCount();
    }
})();