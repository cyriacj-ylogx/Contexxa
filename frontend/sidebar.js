/**
 * sidebar.js — shared sidebar toggle + dark mode logic.
 * Included by both index.html and upload.html.
 */
(function () {
    const SIDEBAR_KEY = "sidebar-expanded";
    const DARK_KEY = "dark-mode";

    function initSidebar() {
        const sidebar = document.getElementById("sidebar");
        const toggle = document.getElementById("sidebar-toggle");
        const themeBtn = document.getElementById("theme-toggle");

        if (!sidebar || !toggle) return;

        // Restore sidebar state
        if (localStorage.getItem(SIDEBAR_KEY) === "true") {
            sidebar.classList.add("expanded");
        }

        toggle.addEventListener("click", () => {
            sidebar.classList.toggle("expanded");
            localStorage.setItem(SIDEBAR_KEY, sidebar.classList.contains("expanded"));
        });

        // Restore dark mode
        if (localStorage.getItem(DARK_KEY) === "true") {
            document.body.classList.add("dark-mode");
            updateThemeIcon(themeBtn, true);
        }

        if (themeBtn) {
            themeBtn.addEventListener("click", () => {
                const isDark = document.body.classList.toggle("dark-mode");
                localStorage.setItem(DARK_KEY, isDark);
                updateThemeIcon(themeBtn, isDark);
            });
        }
    }

    function updateThemeIcon(btn, isDark) {
        if (!btn) return;
        const icon = btn.querySelector("i");
        if (!icon) return;
        if (isDark) {
            icon.classList.remove("fa-moon");
            icon.classList.add("fa-sun");
        } else {
            icon.classList.remove("fa-sun");
            icon.classList.add("fa-moon");
        }
    }

    document.addEventListener("DOMContentLoaded", initSidebar);
})();
