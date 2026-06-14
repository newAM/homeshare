document.querySelectorAll("time[datetime]").forEach((el) => {
  el.textContent = new Date(el.getAttribute("datetime")).toLocaleString(
    undefined,
    { dateStyle: "medium", timeStyle: "short", hour12: false },
  );
});

// Inject a copy-to-clipboard button into the token banner.
// Only added when JS and the clipboard API are both available,
// users with javascript disabled are unaffected and still see the token text
// they can copy manually.
(() => {
  const codeEl = document.querySelector(".token-banner code");
  if (!codeEl || !navigator.clipboard) return;

  const btn = document.createElement("button");
  btn.textContent = "Copy to clipboard";
  btn.className = "btn-copy";

  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(codeEl.textContent.trim()).then(
      () => {
        btn.textContent = "Copied!";
        setTimeout(() => {
          btn.textContent = "Copy to clipboard";
        }, 2000);
      },
      () => {
        btn.textContent = "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy to clipboard";
        }, 2000);
      },
    );
  });

  codeEl.insertAdjacentElement("afterend", btn);
})();

// Upload progress bar.
// Users without JavaScript get the plain HTML form unchanged.
// If the enhanced request fails for any reason we fall back to a normal form
// submission so the upload still completes.
(() => {
  const form = document.querySelector("form[action$='/upload']");
  if (!form) return;
  if (!window.XMLHttpRequest || !window.FormData) return;
  if (!new XMLHttpRequest().upload) return;

  const wrap = document.getElementById("upload-progress-wrap");
  const bar = document.getElementById("upload-progress");
  const label = document.getElementById("upload-progress-label");
  const button = document.getElementById("upload-button");
  if (!wrap || !bar || !label || !button) return;

  const formatBytes = (n) => {
    if (!isFinite(n) || n < 0) return "?";
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let value = n;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i++;
    }
    return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  };

  const reset = () => {
    wrap.hidden = true;
    bar.value = 0;
    label.textContent = "";
    button.disabled = false;
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    const submitNatively = () => {
      // Bypass our own listener so the browser performs a standard submit.
      form.removeEventListener("submit", handleSubmit);
      form.submit();
    };

    const xhr = new XMLHttpRequest();
    xhr.open(form.method || "POST", form.action);
    xhr.responseType = "document";

    // Surface the bar and lock the button while the request is in flight.
    wrap.hidden = false;
    button.disabled = true;

    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        // Guard against a degenerate total of 0 even though
        // lengthComputable should imply total > 0.
        const ratio = ev.total > 0 ? ev.loaded / ev.total : 0;
        bar.value = ratio * 100;
        const pct = Math.round(ratio * 100);
        label.textContent = `${formatBytes(ev.loaded)} / ${formatBytes(ev.total)} (${pct}%)`;
      } else {
        bar.removeAttribute("value");
        label.textContent = formatBytes(ev.loaded);
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 400) {
        // The server redirects (302) to the share detail page; responseURL is
        // the final URL after following redirects.
        if (xhr.responseURL) {
          window.location.href = xhr.responseURL;
        } else {
          window.location.reload();
        }
        return;
      }
      // Any HTTP error: fall back to a native submit.
      reset();
      submitNatively();
    };

    xhr.onerror = () => {
      reset();
      submitNatively();
    };

    xhr.onabort = () => {
      reset();
      submitNatively();
    };

    try {
      xhr.send(new FormData(form));
    } catch (err) {
      reset();
      submitNatively();
    }
  };

  form.addEventListener("submit", handleSubmit);
})();
