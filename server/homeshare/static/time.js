document.querySelectorAll("time[datetime]").forEach(function (el) {
  el.textContent = new Date(el.getAttribute("datetime")).toLocaleString(
    undefined,
    { dateStyle: "medium", timeStyle: "short", hour12: false },
  );
});
