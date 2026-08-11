// Deprecated: superseded by map-ui.js. Kept as a thin shim so that any page
// still held in an older service-worker cache continues to work.
function getColor(mins) { return window.RR ? RR.colour(mins) : '#0072B2'; }

function initMap(lat, lng, zoom) {
  if (window.RR) return RR.createMap('map', { center: [lat, lng], zoom: zoom });
  var map = L.map('map').setView([lat, lng], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
  }).addTo(map);
  return map;
}

function createTerminalMarker(map, lat, lng, popupHtml) {
  return RR.terminalMarker(map, lat, lng, popupHtml);
}

function createStationMarker(map, lat, lng, mins, popupHtml) {
  return RR.stationMarker(map, { lat: lat, lng: lng, name: '' }, mins, popupHtml);
}
