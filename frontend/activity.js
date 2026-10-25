// Activity page: saved runs (Load reopens the results, Delete removes the run).
renderSavedRuns($("runsList"), $("runsCount"));
$("clearBtn").addEventListener("click", () => { clearHistory(); location.reload(); });
