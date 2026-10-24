// Activity page: full session history.
renderActivity($("activityList"), 50);
$("clearBtn").addEventListener("click", () => { clearHistory(); location.reload(); });
