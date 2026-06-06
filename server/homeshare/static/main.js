document.querySelectorAll("time[datetime]").forEach(function (el) {
  el.textContent = new Date(el.getAttribute("datetime")).toLocaleString(
    undefined,
    { dateStyle: "medium", timeStyle: "short", hour12: false },
  );
});

// Inject a copy-to-clipboard button into the token banner.
// Only added when JS and the clipboard API are both available,
// users with javascript disabled are unaffected and still see the token text
// they can copy manually.
(function () {
  var codeEl = document.querySelector(".token-banner code");
  if (!codeEl || !navigator.clipboard) return;

  var btn = document.createElement("button");
  btn.textContent = "Copy to clipboard";
  btn.className = "btn-copy";

  btn.addEventListener("click", function () {
    navigator.clipboard.writeText(codeEl.textContent.trim()).then(
      function () {
        btn.textContent = "Copied!";
        setTimeout(function () {
          btn.textContent = "Copy to clipboard";
        }, 2000);
      },
      function () {
        btn.textContent = "Copy failed";
        setTimeout(function () {
          btn.textContent = "Copy to clipboard";
        }, 2000);
      },
    );
  });

  codeEl.insertAdjacentElement("afterend", btn);
})();
