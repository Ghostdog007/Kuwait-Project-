// ── Trip Map Application (Identifier-Based) ──
// Day → Drive → Trip cascading selector with single-trip focus view.

let mapData = null;
let map = null;
let directionsService = null;
let depotMarker = null;
let routeCache = {};
let activeRenderers = [];
let activeMarkers = [];

const COLORS = { IN: '#34d399', OUT: '#fb7185', MIXED: '#a78bfa' };
const KUWAIT_CENTER = { lat: 29.18, lng: 48.10 };

// ── DOM refs ──
const daySelect = () => document.getElementById('daySelect');
const driveSelect = () => document.getElementById('driveSelect');
const tripSelect = () => document.getElementById('tripSelect');
const showTripBtn = () => document.getElementById('showTripBtn');
const showAllBtn = () => document.getElementById('showAllBtn');

// ── Init ──
async function initApp(apiKey) {
  document.getElementById('apiKeyPrompt').classList.add('hidden');
  document.getElementById('loadingOverlay').classList.remove('hidden');

  const resp = await fetch('map_data.json');
  mapData = await resp.json();

  await loadGoogleMaps(apiKey);

  map = new google.maps.Map(document.getElementById('map'), {
    center: KUWAIT_CENTER,
    zoom: 11,
    styles: darkMapStyle,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: true,
    zoomControl: true,
  });
  directionsService = new google.maps.DirectionsService();

  depotMarker = new google.maps.Marker({
    position: { lat: mapData.depot.lat, lng: mapData.depot.lng },
    map: map,
    title: mapData.depot.name,
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 12,
      fillColor: '#fbbf24',
      fillOpacity: 1,
      strokeColor: '#f59e0b',
      strokeWeight: 3,
    },
    zIndex: 1000,
  });

  depotMarker.addListener('click', () => {
    new google.maps.InfoWindow({
      content: `<div class="info-window">
        <h3>🏠 ${mapData.depot.name}</h3>
        <p style="font-size:12px;color:#64748b">Depot — All trips start and end here</p>
      </div>`
    }).open(map, depotMarker);
  });

  populateDays();
  setupListeners();

  document.getElementById('loadingOverlay').classList.add('hidden');
}

function loadGoogleMaps(apiKey) {
  return new Promise((resolve, reject) => {
    if (window.google && google.maps) { resolve(); return; }
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=geometry`;
    script.async = true;
    script.onload = resolve;
    script.onerror = () => reject(new Error('Failed to load Google Maps'));
    document.head.appendChild(script);
  });
}

// ── Cascading Selectors ──
function populateDays() {
  const sel = daySelect();
  mapData.days.forEach(day => {
    const opt = document.createElement('option');
    opt.value = day;
    const date = new Date(day + 'T00:00:00');
    opt.textContent = `${day} (${date.toLocaleDateString('en-US', { weekday: 'long' })})`;
    sel.appendChild(opt);
  });
}

function populateDrives(day) {
  const sel = driveSelect();
  sel.innerHTML = '<option value="" disabled selected>Select a drive…</option>';
  sel.disabled = false;

  const drives = mapData.index[day] || {};
  // Add "All Drives" option
  const allOpt = document.createElement('option');
  allOpt.value = '__ALL__';
  allOpt.textContent = `All Drives (${Object.keys(drives).length})`;
  sel.appendChild(allOpt);

  Object.keys(drives).forEach(drive => {
    const opt = document.createElement('option');
    opt.value = drive;
    const tripCount = drives[drive].length;
    opt.textContent = `${drive} — ${tripCount} trip${tripCount > 1 ? 's' : ''}`;
    sel.appendChild(opt);
  });

  // Reset trip select
  const tSel = tripSelect();
  tSel.innerHTML = '<option value="" disabled selected>Select a trip…</option>';
  tSel.disabled = true;
  showTripBtn().disabled = true;
  showAllBtn().disabled = false;
}

function populateTrips(day, drive) {
  const sel = tripSelect();
  sel.innerHTML = '<option value="" disabled selected>Select a trip…</option>';

  if (drive === '__ALL__') {
    sel.disabled = true;
    showTripBtn().disabled = true;
    return;
  }

  sel.disabled = false;
  const trips = (mapData.index[day] || {})[drive] || [];

  // Add "All Trips" for this drive
  const allOpt = document.createElement('option');
  allOpt.value = '__ALL__';
  allOpt.textContent = `All Trips for ${drive} (${trips.length})`;
  sel.appendChild(allOpt);

  trips.forEach(tripId => {
    const trip = findTrip(day, drive, tripId);
    const opt = document.createElement('option');
    opt.value = tripId;
    const pax = trip ? (trip.employeeCount || trip.stops.reduce((s, st) => s + st.passengerCount, 0)) : '?';
    opt.textContent = `${tripId} — ${trip ? trip.tripStart + ' → ' + trip.tripEnd : ''} (${pax} pax)`;
    sel.appendChild(opt);
  });

  showTripBtn().disabled = false;
}

function findTrip(day, drive, tripId) {
  return mapData.trips.find(t => t.day === day && t.drive === drive && t.tripId === tripId);
}

function getFilteredTrips() {
  const day = daySelect().value;
  const drive = driveSelect().value;
  const tripId = tripSelect().value;

  if (!day) return [];
  let trips = mapData.trips.filter(t => t.day === day);
  if (drive && drive !== '__ALL__') {
    trips = trips.filter(t => t.drive === drive);
    if (tripId && tripId !== '__ALL__') {
      trips = trips.filter(t => t.tripId === tripId);
    }
  }
  return trips;
}

// ── Listeners ──
function setupListeners() {
  daySelect().addEventListener('change', () => {
    const day = daySelect().value;
    populateDrives(day);
    clearMap();
    hideAllPanels();
  });

  driveSelect().addEventListener('change', () => {
    const day = daySelect().value;
    const drive = driveSelect().value;
    populateTrips(day, drive);
  });

  tripSelect().addEventListener('change', () => {
    showTripBtn().disabled = false;
  });

  showTripBtn().addEventListener('click', () => {
    const trips = getFilteredTrips();
    if (trips.length === 0) return;
    clearMap();
    if (trips.length === 1) {
      renderSingleTrip(trips[0]);
    } else {
      renderAllTripsView(trips);
    }
  });

  showAllBtn().addEventListener('click', () => {
    const day = daySelect().value;
    if (!day) return;
    const trips = mapData.trips.filter(t => t.day === day);
    clearMap();
    renderAllTripsView(trips);
  });

  document.getElementById('routeToggle').addEventListener('change', () => {
    // Re-render current view
    const trips = getFilteredTrips();
    if (trips.length === 0) {
      const day = daySelect().value;
      if (day) {
        const allTrips = mapData.trips.filter(t => t.day === day);
        if (allTrips.length > 0) { clearMap(); renderAllTripsView(allTrips); }
      }
      return;
    }
    clearMap();
    if (trips.length === 1) renderSingleTrip(trips[0]);
    else renderAllTripsView(trips);
  });
}

// ── Clear ──
function clearMap() {
  activeRenderers.forEach(r => { if (r.setMap) r.setMap(null); });
  activeMarkers.forEach(m => { if (m.setMap) m.setMap(null); });
  activeRenderers = [];
  activeMarkers = [];
}

function hideAllPanels() {
  document.getElementById('tripDetail').classList.remove('visible');
  document.getElementById('tripListHeader').style.display = 'none';
  document.getElementById('tripList').style.display = 'none';
}

// ── Render Single Trip ──
function renderSingleTrip(trip) {
  hideAllPanels();

  // Show detail panel
  const detail = document.getElementById('tripDetail');
  detail.classList.add('visible');

  const color = COLORS[trip.type] || '#60a5fa';
  const pax = trip.employeeCount || trip.stops.reduce((s, st) => s + st.passengerCount, 0);

  // Header
  document.getElementById('tripDetailHeader').innerHTML = `
    <div class="detail-title">${trip.drive} / ${trip.tripId}</div>
    <span class="detail-badge ${trip.type.toLowerCase()}">${trip.type}</span>
  `;

  // Body with meta cards + stop timeline + employees
  const body = document.getElementById('tripDetailBody');
  body.innerHTML = `
    <div class="detail-meta">
      <div class="meta-card"><div class="meta-label">Departure</div><div class="meta-value">${trip.tripStart}</div></div>
      <div class="meta-card"><div class="meta-label">Arrival</div><div class="meta-value">${trip.tripEnd}</div></div>
      <div class="meta-card"><div class="meta-label">Stops</div><div class="meta-value">${trip.stops.length}</div></div>
      <div class="meta-card"><div class="meta-label">Passengers</div><div class="meta-value">${pax}</div></div>
    </div>
    <div class="detail-section-title">Route Timeline</div>
    <div class="stop-timeline" id="stopTimeline"></div>
    <div class="detail-section-title">Employees (${trip.employees.length})</div>
    <div class="employee-list" id="employeeList"></div>
  `;

  // Build stop timeline
  const timeline = document.getElementById('stopTimeline');
  // Trip Start
  timeline.innerHTML = `
    <div class="stop-item depot-stop" data-num="">
      <div class="stop-name">🏠 Mahboula Depot</div>
      <div class="stop-meta">Trip Start · ${trip.tripStart}</div>
    </div>
  `;

  trip.stops.forEach((stop, i) => {
    const item = document.createElement('div');
    item.className = `stop-item ${trip.type.toLowerCase()}`;
    item.dataset.num = String(i + 1);
    item.innerHTML = `
      <div class="stop-name">${stop.name}</div>
      <div class="stop-meta">Store ID: ${stop.storeId} · ${stop.passengerCount} passengers</div>
      <div class="stop-meta">Scheduled: ${stop.scheduledTime}</div>
      <div class="stop-eta" id="eta-${i}"></div>
    `;
    item.addEventListener('click', () => {
      if (stop.lat && stop.lng) {
        map.panTo({ lat: stop.lat, lng: stop.lng });
        map.setZoom(14);
        const marker = activeMarkers.find(m => m._stopIdx === i);
        if (marker) google.maps.event.trigger(marker, 'click');
      }
    });
    timeline.appendChild(item);
  });

  // Trip End
  timeline.innerHTML += `
    <div class="stop-item depot-stop" data-num="">
      <div class="stop-name">🏠 Mahboula Depot</div>
      <div class="stop-meta">Trip End · ${trip.tripEnd}</div>
    </div>
  `;

  // Employee list
  const empList = document.getElementById('employeeList');
  if (trip.employees.length > 0) {
    trip.employees.forEach(e => {
      const row = document.createElement('div');
      row.className = 'employee-row';
      row.innerHTML = `<span class="employee-name">${e.name || 'Unknown'}</span><span class="employee-code">${e.code}</span>`;
      empList.appendChild(row);
    });
  } else {
    empList.innerHTML = '<div style="font-size:12px;color:#64748b;padding:8px 0">No employee data</div>';
  }

  // Render on map
  renderTripOnMap(trip);

  // Fit bounds
  const bounds = new google.maps.LatLngBounds();
  bounds.extend({ lat: mapData.depot.lat, lng: mapData.depot.lng });
  trip.stops.forEach(s => { if (s.lat && s.lng) bounds.extend({ lat: s.lat, lng: s.lng }); });
  map.fitBounds(bounds, 80);
}

// ── Render All Trips View ──
function renderAllTripsView(trips) {
  hideAllPanels();

  // Show trip list
  document.getElementById('tripListHeader').style.display = 'block';
  document.getElementById('tripListHeader').textContent = `${trips.length} Trips`;
  const container = document.getElementById('tripList');
  container.style.display = 'block';
  container.innerHTML = '';

  trips.sort((a, b) => {
    if (a.drive !== b.drive) return a.drive.localeCompare(b.drive, undefined, { numeric: true });
    return a.tripId.localeCompare(b.tripId, undefined, { numeric: true });
  });

  trips.forEach(trip => {
    const pax = trip.employeeCount || trip.stops.reduce((s, st) => s + st.passengerCount, 0);
    const card = document.createElement('div');
    card.className = 'trip-card';
    card.innerHTML = `
      <div class="trip-badge ${trip.type.toLowerCase()}"></div>
      <div class="trip-card-info">
        <div class="trip-card-title">${trip.drive} / ${trip.tripId}</div>
        <div class="trip-card-meta">${trip.tripStart} – ${trip.tripEnd} · ${trip.stops.length} stops</div>
      </div>
      <div class="trip-card-pax">${pax} 👤</div>
    `;
    card.addEventListener('click', () => {
      // Set selectors and show single trip
      driveSelect().value = trip.drive;
      populateTrips(trip.day, trip.drive);
      tripSelect().value = trip.tripId;
      showTripBtn().disabled = false;
      clearMap();
      renderSingleTrip(trip);
    });
    container.appendChild(card);
  });

  // Render all on map
  trips.forEach(trip => renderTripOnMap(trip));

  // Fit bounds
  const bounds = new google.maps.LatLngBounds();
  bounds.extend({ lat: mapData.depot.lat, lng: mapData.depot.lng });
  trips.forEach(trip => {
    trip.stops.forEach(s => { if (s.lat && s.lng) bounds.extend({ lat: s.lat, lng: s.lng }); });
  });
  map.fitBounds(bounds, 60);
}

// ── Render a trip on map ──
async function renderTripOnMap(trip) {
  const color = COLORS[trip.type] || '#60a5fa';
  const validStops = trip.stops.filter(s => s.lat && s.lng);
  if (validStops.length === 0) return;

  const depotPos = { lat: mapData.depot.lat, lng: mapData.depot.lng };
  const useDirections = document.getElementById('routeToggle').checked;

  if (useDirections) {
    await renderDirectionsRoute(trip, validStops, color, depotPos);
  } else {
    const points = [depotPos, ...validStops.map(s => ({ lat: s.lat, lng: s.lng })), depotPos];
    const polyline = new google.maps.Polyline({
      path: points,
      strokeColor: color,
      strokeOpacity: 0.85,
      strokeWeight: 4,
      map: map,
      zIndex: 3,
    });
    activeRenderers.push(polyline);
  }

  // Stop markers
  validStops.forEach((stop, idx) => {
    const marker = new google.maps.Marker({
      position: { lat: stop.lat, lng: stop.lng },
      map: map,
      title: stop.name,
      label: { text: String(idx + 1), color: '#fff', fontSize: '10px', fontWeight: '700' },
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 11,
        fillColor: color,
        fillOpacity: 0.9,
        strokeColor: '#fff',
        strokeWeight: 2,
      },
      zIndex: 5,
    });
    marker._stopIdx = idx;
    marker._stopData = { stop, trip, idx };
    marker.addListener('click', () => openStopInfo(marker));
    activeMarkers.push(marker);
  });
}

async function renderDirectionsRoute(trip, validStops, color, depotPos) {
  const cacheKey = `${trip.day}-${trip.drive}-${trip.tripId}`;

  if (routeCache[cacheKey]) {
    drawCachedRoute(routeCache[cacheKey], color);
    attachETAs(routeCache[cacheKey], trip, validStops);
    return;
  }

  const request = {
    origin: depotPos,
    destination: depotPos,
    waypoints: validStops.map(s => ({ location: { lat: s.lat, lng: s.lng }, stopover: true })),
    travelMode: 'DRIVING',
    optimizeWaypoints: false,
  };

  try {
    const result = await new Promise((resolve, reject) => {
      directionsService.route(request, (result, status) => {
        if (status === 'OK') resolve(result);
        else reject(new Error(status));
      });
    });
    routeCache[cacheKey] = result;
    drawCachedRoute(result, color);
    attachETAs(result, trip, validStops);
  } catch {
    // Fallback polyline
    const points = [depotPos, ...validStops.map(s => ({ lat: s.lat, lng: s.lng })), depotPos];
    const polyline = new google.maps.Polyline({
      path: points, strokeColor: color, strokeOpacity: 0.5, strokeWeight: 3,
      geodesic: true, map: map, zIndex: 3,
    });
    activeRenderers.push(polyline);
  }
}

function drawCachedRoute(result, color) {
  const path = [];
  result.routes[0].legs.forEach(leg => {
    leg.steps.forEach(step => { step.path.forEach(p => path.push(p)); });
  });
  const polyline = new google.maps.Polyline({
    path, strokeColor: color, strokeOpacity: 0.85, strokeWeight: 5, map, zIndex: 3,
  });
  activeRenderers.push(polyline);
}

function attachETAs(result, trip, validStops) {
  const legs = result.routes[0].legs;
  let cumSec = 0;
  for (let i = 0; i < validStops.length && i < legs.length; i++) {
    cumSec += legs[i].duration.value;
    validStops[i]._gmapCumulativeEta = formatSec(cumSec);
    validStops[i]._gmapLegDist = legs[i].distance.text;
    validStops[i]._gmapLegTime = legs[i].duration.text;
    // Update sidebar ETA
    const etaEl = document.getElementById(`eta-${i}`);
    if (etaEl) etaEl.textContent = `Maps ETA: ${formatSec(cumSec)} from depot · ${legs[i].distance.text}`;
  }
}

function formatSec(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// ── InfoWindow ──
function openStopInfo(marker) {
  const { stop, trip, idx } = marker._stopData;
  const employees = trip.employees || [];
  const empList = employees.length > 0
    ? employees.map(e => e.name ? `${e.name} <span style="color:#94a3b8">(${e.code})</span>` : e.code).join('<br>')
    : '<span style="color:#94a3b8">No employee data</span>';

  const gmapEta = stop._gmapCumulativeEta
    ? `<div class="info-row"><span class="info-label">Maps ETA (from depot)</span><span class="info-value">${stop._gmapCumulativeEta}</span></div>
       <div class="info-row"><span class="info-label">Leg distance</span><span class="info-value">${stop._gmapLegDist || '—'}</span></div>`
    : '';

  const html = `
    <div class="info-window">
      <h3>${stop.name}</h3>
      <span class="info-badge-iw ${trip.type.toLowerCase()}">${trip.type}</span>
      <div class="info-row"><span class="info-label">Stop</span><span class="info-value">#${idx + 1} of ${trip.stops.length}</span></div>
      <div class="info-row"><span class="info-label">Store ID</span><span class="info-value">${stop.storeId}</span></div>
      <div class="info-row"><span class="info-label">Passengers</span><span class="info-value">${stop.passengerCount}</span></div>
      <div class="info-row"><span class="info-label">Scheduled</span><span class="info-value">${stop.scheduledTime}</span></div>
      ${gmapEta}
      <div class="info-row"><span class="info-label">Trip</span><span class="info-value">${trip.drive} / ${trip.tripId} · ${trip.tripStart}–${trip.tripEnd}</span></div>
      <div class="info-section-title">Employees (${trip.employeeCount || employees.length})</div>
      <div class="info-employees">${empList}</div>
    </div>`;
  new google.maps.InfoWindow({ content: html, maxWidth: 340 }).open(map, marker);
}

// ── Dark Map Style ──
const darkMapStyle = [
  { elementType: 'geometry', stylers: [{ color: '#1a1a2e' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#1a1a2e' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#8892b0' }] },
  { featureType: 'administrative', elementType: 'geometry', stylers: [{ color: '#2d2d4a' }] },
  { featureType: 'poi', elementType: 'geometry', stylers: [{ color: '#222244' }] },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#6c7293' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#2a2a4a' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#333366' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#3a3a5c' }] },
  { featureType: 'road.highway', elementType: 'geometry.stroke', stylers: [{ color: '#4a4a6a' }] },
  { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#2a2a4a' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e1538' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#4a5568' }] },
];

// ── Boot ──
window.addEventListener('DOMContentLoaded', () => {
  const envKey = window.GMAPS_API_KEY;
  const savedKey = localStorage.getItem('gmaps_api_key');
  const apiKey = (envKey && envKey !== 'YOUR_API_KEY_HERE') ? envKey : savedKey;

  if (apiKey) {
    initApp(apiKey);
  } else {
    document.getElementById('apiKeyPrompt').classList.remove('hidden');
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('apiKeySubmit').addEventListener('click', () => {
      const key = document.getElementById('apiKeyInput').value.trim();
      if (!key) return;
      localStorage.setItem('gmaps_api_key', key);
      initApp(key);
    });
    document.getElementById('apiKeyInput').addEventListener('keydown', e => {
      if (e.key === 'Enter') document.getElementById('apiKeySubmit').click();
    });
  }
});
