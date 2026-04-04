(function () {
  "use strict";

  const pwdNew     = document.getElementById("pwd-new");
  const pwdConfirm = document.getElementById("pwd-confirm");
  const submitBtn  = document.getElementById("pwd-submit");
  const segments   = document.querySelectorAll(".strength-seg");
  const hibpStatus = document.getElementById("hibp-status");

  const ruleEls = {
    length:  document.getElementById("rule-length"),
    upper:   document.getElementById("rule-upper"),
    lower:   document.getElementById("rule-lower"),
    digit:   document.getElementById("rule-digit"),
    special: document.getElementById("rule-special"),
  };

  if (!pwdNew || !submitBtn) return;

  // ── State ─────────────────────────────────────────────────────────
  let hibpClean    = false;
  let hibpChecking = false;
  let hibpTimer    = null;
  let lastChecked  = "";

  // ── Complexity ────────────────────────────────────────────────────
  function checkComplexity(pwd) {
    return {
      length:  pwd.length >= 12,
      upper:   /[A-Z]/.test(pwd),
      lower:   /[a-z]/.test(pwd),
      digit:   /[0-9]/.test(pwd),
      special: /[!@#$%^&*()\-_=+[\]{}|;:,.<>?]/.test(pwd),
    };
  }

  function allPass(r) {
    return Object.values(r).every(Boolean);
  }

  // ── SHA-1 via SubtleCrypto ────────────────────────────────────────
  async function sha1Hex(str) {
    const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase();
  }

  // ── HIBP ──────────────────────────────────────────────────────────
  async function checkHIBP(pwd) {
    if (pwd === lastChecked && hibpClean) return;
    lastChecked  = pwd;
    hibpChecking = true;
    hibpClean    = false;

    if (hibpStatus) {
      hibpStatus.textContent = "Checking against known breaches\u2026";
      hibpStatus.className   = "hibp-status hibp-checking";
    }
    updateSubmit();

    try {
      const hash   = await sha1Hex(pwd);
      const prefix = hash.slice(0, 5);
      const suffix = hash.slice(5);

      const resp = await fetch(
        `https://api.pwnedpasswords.com/range/${prefix}`,
        { headers: { "Add-Padding": "true" } }
      );
      if (!resp.ok) throw new Error("API error");

      let count = 0;
      for (const line of (await resp.text()).split("\n")) {
        const [s, c] = line.split(":");
        if (s && s.trim() === suffix) {
          count = parseInt(c, 10);
          break;
        }
      }

      if (count > 0) {
        hibpClean = false;
        if (hibpStatus) {
          hibpStatus.textContent = `Found in ${count.toLocaleString()} known data breaches \u2014 choose a different password.`;
          hibpStatus.className   = "hibp-status hibp-breached";
        }
      } else {
        hibpClean = true;
        if (hibpStatus) {
          hibpStatus.textContent = "Not found in any known breach \u2713";
          hibpStatus.className   = "hibp-status hibp-clean";
        }
      }
    } catch {
      hibpClean = true;
      if (hibpStatus) {
        hibpStatus.textContent = "Breach check unavailable \u2014 proceeding.";
        hibpStatus.className   = "hibp-status hibp-warn";
      }
    } finally {
      hibpChecking = false;
      updateSubmit();
    }
  }

  // ── UI updates ────────────────────────────────────────────────────
  function updateChecklist(r) {
    for (const [key, el] of Object.entries(ruleEls)) {
      if (!el) continue;
      const pass = r[key];
      el.className = "pwd-rule " + (pass ? "rule-pass" : "rule-fail");
      const icon = el.querySelector(".rule-icon");
      if (icon) icon.textContent = pass ? "\u2713" : "\u2715";
    }
  }

  const SEG_COLORS = ["#dc2626", "#d97706", "#059669", "#0d9488"];

  function updateStrengthBar(r, hibpOk) {
    const count  = Object.values(r).filter(Boolean).length;
    const level  = count <= 1 ? 0 : count <= 3 ? 1 : hibpOk ? 3 : 2;
    const filled = level + 1;
    segments.forEach((seg, i) => {
      seg.style.background = i < filled ? SEG_COLORS[level] : "#e2e8f0";
    });
  }

  function confirmMatches() {
    if (!pwdConfirm || pwdConfirm.value === "") return true;
    return pwdConfirm.value === pwdNew.value;
  }

  function updateSubmit() {
    const r     = checkComplexity(pwdNew.value);
    const ready = allPass(r) && hibpClean && !hibpChecking && confirmMatches();
    submitBtn.disabled = !ready;
  }

  // ── Password input handler ────────────────────────────────────────
  function onNewPasswordInput() {
    const pwd = pwdNew.value;
    const r   = checkComplexity(pwd);

    updateChecklist(r);
    updateStrengthBar(r, hibpClean);

    // Reset HIBP if password changed from last check
    if (pwd !== lastChecked) {
      hibpClean    = false;
      hibpChecking = false;
      if (hibpStatus) {
        hibpStatus.textContent = "";
        hibpStatus.className   = "hibp-status";
      }
    }

    updateSubmit();
    clearTimeout(hibpTimer);

    if (!allPass(r) || pwd.length === 0) return;
    hibpTimer = setTimeout(() => checkHIBP(pwd), 600);
  }

  pwdNew.addEventListener("input", onNewPasswordInput);
  if (pwdConfirm) pwdConfirm.addEventListener("input", updateSubmit);

  // ── Show/hide toggles ─────────────────────────────────────────────
  document.querySelectorAll("[data-toggle-pwd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.getAttribute("data-toggle-pwd"));
      if (!input) return;
      const hidden    = input.type === "password";
      input.type      = hidden ? "text" : "password";
      btn.textContent = hidden ? "Hide" : "Show";
    });
  });
})();
