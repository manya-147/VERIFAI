// Dashboard: stats and recent activity.
$("statSearches").textContent = store.searches;
$("statListings").textContent = store.listings;
$("statLinks").textContent = store.links;
$("statRate").textContent = store.searches ? Math.round((store.ok / store.searches) * 100) + "%" : "—";
renderActivity($("activityList"), 5);
