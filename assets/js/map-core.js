// Shared map utilities for RailReach spoke pages
function getColor(mins) {
  if (mins < 30) return '#22c55e';
  if (mins < 60) return '#f59e0b';
  return '#ef4444';
}

function initMap(lat, lng, zoom) {
  const map = L.map('map').setView([lat, lng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
  }).addTo(map);
  return map;
}

// NOTE: keep these names stable. Visitors carrying an older service-worker
// cache may be served a stale copy of this file against fresh HTML; renaming
// an exported function would break every map on the site for them.
function createTerminalMarker(map, lat, lng, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 12, fillColor: '#7c3aed', color: '#fff',
    weight: 3, opacity: 1, fillOpacity: 0.9
  }).bindPopup(popupHtml).addTo(map);
}

function createStationMarker(map, lat, lng, mins, popupHtml) {
  return L.circleMarker([lat, lng], {
    radius: 7, fillColor: getColor(mins), color: '#fff',
    weight: 2, opacity: 1, fillOpacity: 0.85
  }).bindPopup(popupHtml).addTo(map);
}
