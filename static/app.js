const API = '';
let currentFilter = '';
let pollTimer = null;
let searchTimer = null;
let selectedVenueId = '';
let skipNextInput = false;

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('reservation-form').addEventListener('submit', handleSubmit);
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => setFilter(btn.dataset.status));
    });
    document.querySelector('.modal-close').addEventListener('click', closeModal);
    document.getElementById('detail-modal').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeModal();
    });

    // Autocomplete
    const input = document.getElementById('restaurant-input');
    const results = document.getElementById('autocomplete-results');
    input.addEventListener('input', () => {
        if (skipNextInput) { skipNextInput = false; return; }
        selectedVenueId = '';
        document.getElementById('venue-id').value = '';
        clearTimeout(searchTimer);
        const q = input.value.trim();
        if (q.length < 2) { results.classList.add('hidden'); return; }
        results.innerHTML = '<div class="autocomplete-loading">Searching Resy...</div>';
        results.classList.remove('hidden');
        searchTimer = setTimeout(() => searchVenues(q), 350);
    });
    input.addEventListener('focus', () => {
        if (input.value.trim().length >= 2 && results.children.length > 0) {
            results.classList.remove('hidden');
        }
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.autocomplete-wrapper')) {
            results.classList.add('hidden');
        }
    });

    // Set default date to tomorrow
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.querySelector('input[name="date"]').value = tomorrow.toISOString().split('T')[0];

    loadStatus();
    loadReservations();
    loadActivity();
    pollTimer = setInterval(() => {
        loadReservations();
        loadActivity();
        loadStatus();
    }, 5000);
});

// --- Venue search autocomplete ---
async function searchVenues(query) {
    const results = document.getElementById('autocomplete-results');
    try {
        const venues = await apiCall(`/api/reservations/search/venues?q=${encodeURIComponent(query)}`);
        if (!venues.length) {
            results.innerHTML = '<div class="autocomplete-loading">No results found</div>';
            return;
        }
        results.innerHTML = venues.map((v, i) => `
            <div class="autocomplete-item" data-index="${i}" data-venue-id="${esc(v.venue_id)}" data-name="${esc(v.name)}">
                <div class="ac-name">${esc(v.name)}</div>
                <div class="ac-meta">${esc(v.neighborhood || v.region || '')}${v.cuisine && v.cuisine.length ? ' &middot; ' + esc(v.cuisine[0]) : ''}</div>
            </div>
        `).join('');
        results.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                const name = item.dataset.name;
                const venueId = item.dataset.venueId;
                skipNextInput = true;
                document.getElementById('restaurant-input').value = name;
                document.getElementById('venue-id').value = venueId;
                selectedVenueId = venueId;
                results.classList.add('hidden');
            });
        });
    } catch (err) {
        results.innerHTML = '<div class="autocomplete-loading">Search failed</div>';
    }
}

// --- API calls ---
async function apiCall(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
    }
    return res.json();
}

// --- Form submit ---
async function handleSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const data = Object.fromEntries(new FormData(form));
    data.party_size = parseInt(data.party_size, 10);
    // Convert booking_open_time empty string to null
    if (!data.booking_open_time) {
        delete data.booking_open_time;
    }
    try {
        await apiCall('/api/reservations', { method: 'POST', body: JSON.stringify(data) });
        toast('Reservation request submitted', 'success');
        form.reset();
        // Reset date to tomorrow
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        form.querySelector('input[name="date"]').value = tomorrow.toISOString().split('T')[0];
        form.querySelector('input[name="time"]').value = '19:00';
        form.querySelector('input[name="party_size"]').value = '2';
        loadReservations();
    } catch (err) {
        toast('Failed: ' + err.message, 'error');
    }
}

// --- Load data ---
async function loadReservations() {
    try {
        const path = currentFilter
            ? `/api/reservations?status=${currentFilter}`
            : '/api/reservations';
        const reservations = await apiCall(path);
        renderReservations(reservations);
    } catch (err) {
        console.error('Failed to load reservations', err);
    }
}

async function loadActivity() {
    try {
        const logs = await apiCall('/api/activity?limit=30');
        renderActivity(logs);
    } catch (err) {
        console.error('Failed to load activity', err);
    }
}

async function loadStatus() {
    try {
        const status = await apiCall('/api/status');
        renderStatus(status);
    } catch (err) {
        console.error('Failed to load status', err);
    }
}

// --- Render ---
function renderStatus(s) {
    const el = document.getElementById('system-status');
    el.innerHTML = `
        <span>${s.total_requests} requests</span>
        <span>${s.active_snipers} sniping</span>
        <span>${s.total_bookings} booked</span>
    `;
}

function renderReservations(list) {
    const container = document.getElementById('reservations-list');
    if (!list.length) {
        container.innerHTML = '<div class="empty">No reservations yet</div>';
        return;
    }
    container.innerHTML = list.map(r => {
        let extra = '';
        if (r.status === 'waiting' && r.booking_open_time) {
            const opensAt = new Date(r.booking_open_time);
            const now = new Date();
            const diffMs = opensAt - now;
            if (diffMs > 0) {
                const mins = Math.floor(diffMs / 60000);
                const secs = Math.floor((diffMs % 60000) / 1000);
                extra = `<span class="sniper-info">Opens in ${mins}m ${secs}s</span>`;
            } else {
                extra = `<span class="sniper-info">Opening now...</span>`;
            }
        } else if (r.status === 'polling') {
            extra = `<span class="sniper-info">${r.poll_attempts} attempts</span>`;
        }

        return `
        <div class="res-item" onclick="showDetail(${r.id})">
            <div class="res-info">
                <div class="res-name">${esc(r.restaurant_name)}</div>
                <div class="res-details">${r.date} at ${r.time} &middot; ${r.party_size} guests${r.platform ? ' &middot; ' + r.platform : ''}</div>
            </div>
            ${extra}
            <span class="badge ${r.status}">${r.status.replace(/_/g, ' ')}</span>
            <div class="res-actions">
                ${r.status !== 'booked' && r.status !== 'cancelled' ? `
                    <button onclick="event.stopPropagation(); retryRes(${r.id})">Retry</button>
                    <button class="danger" onclick="event.stopPropagation(); cancelRes(${r.id})">Cancel</button>
                ` : ''}
            </div>
        </div>`;
    }).join('');
}

function renderActivity(logs) {
    const container = document.getElementById('activity-log');
    if (!logs.length) {
        container.innerHTML = '<div class="empty">No activity yet</div>';
        return;
    }
    container.innerHTML = logs.map(l => `
        <div class="log-entry">
            <span class="log-time">${new Date(l.timestamp).toLocaleString()}</span>
            <span class="log-action">${esc(l.action)}</span>
            <span class="log-platform">${l.platform || ''}</span>
            <span class="log-details">${l.details ? esc(truncate(l.details, 80)) : ''}</span>
        </div>
    `).join('');
}

// --- Actions ---
async function retryRes(id) {
    try {
        await apiCall(`/api/reservations/${id}/retry`, { method: 'POST' });
        toast('Retrying reservation...', 'success');
        loadReservations();
    } catch (err) {
        toast('Retry failed: ' + err.message, 'error');
    }
}

async function cancelRes(id) {
    if (!confirm('Cancel this reservation request?')) return;
    try {
        await apiCall(`/api/reservations/${id}`, { method: 'DELETE' });
        toast('Cancelled', 'success');
        loadReservations();
    } catch (err) {
        toast('Cancel failed: ' + err.message, 'error');
    }
}

async function showDetail(id) {
    try {
        const detail = await apiCall(`/api/reservations/${id}`);
        renderModal(detail);
        document.getElementById('detail-modal').classList.remove('hidden');
    } catch (err) {
        toast('Failed to load details', 'error');
    }
}

function renderModal(d) {
    const body = document.getElementById('modal-body');
    let sniperInfo = '';
    if (d.booking_open_time) {
        sniperInfo = `<p style="color:#666; margin: 0.25rem 0">Booking opens: ${new Date(d.booking_open_time).toLocaleString()}</p>`;
    }
    if (d.poll_attempts > 0) {
        sniperInfo += `<p style="color:#666; margin: 0.25rem 0">Poll attempts: ${d.poll_attempts}</p>`;
    }

    body.innerHTML = `
        <h2>${esc(d.restaurant_name)} <span class="badge ${d.status}">${d.status.replace(/_/g, ' ')}</span></h2>
        <p style="color:#777; margin: 0.5rem 0">${d.date} at ${d.time} &middot; ${d.party_size} guests</p>
        ${sniperInfo}

        ${d.bookings.length ? `
        <div class="modal-section">
            <h3>Bookings</h3>
            ${d.bookings.map(b => `
                <div style="padding:0.4rem 0; border-bottom:1px solid #eee">
                    <strong>${b.platform}</strong> &middot; ${b.date} ${b.time} &middot;
                    Confirmation: ${b.confirmation_id || 'N/A'} &middot;
                    <span class="badge booked">${b.status}</span>
                </div>
            `).join('')}
        </div>` : ''}

        ${d.logs.length ? `
        <div class="modal-section">
            <h3>Activity Log</h3>
            ${d.logs.map(l => `
                <div class="log-entry">
                    <span class="log-time">${new Date(l.timestamp).toLocaleString()}</span>
                    <span class="log-action">${esc(l.action)}</span>
                    <span class="log-platform">${l.platform || ''}</span>
                </div>
            `).join('')}
        </div>` : ''}
    `;
}

function closeModal() {
    document.getElementById('detail-modal').classList.add('hidden');
}

// --- Filters ---
function setFilter(status) {
    currentFilter = status;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.filter-btn[data-status="${status}"]`).classList.add('active');
    loadReservations();
}

// --- Toast ---
function toast(msg, type = '') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// --- Utils ---
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function truncate(s, n) {
    return s.length > n ? s.slice(0, n) + '...' : s;
}
