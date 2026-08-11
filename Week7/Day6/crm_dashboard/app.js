document.addEventListener('DOMContentLoaded', () => {
    // Initialize Lucide icons
    lucide.createIcons();

    // Navigation setup
    const navBtns = document.querySelectorAll('.nav-btn');
    const views = document.querySelectorAll('.view');
    const pageTitle = document.getElementById('page-title');
    
    const titles = {
        'dashboard': 'Dashboard Overview',
        'clients': 'Client Database',
        'appointments': 'Appointments History',
        'events': 'Events Trail',
        'reminders': 'Follow-up Reminders'
    };

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            
            // Update active state
            navBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Show target view
            views.forEach(v => v.classList.remove('active'));
            document.getElementById(targetId).classList.add('active');
            
            // Update title
            pageTitle.textContent = titles[targetId];
            
            // Load data for view if needed
            loadData(targetId);
        });
    });

    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', () => {
        const activeView = document.querySelector('.view.active').id;
        loadData(activeView, true);
        loadDashboardStats(); // Always refresh stats on manual refresh
    });

    // Modal close
    document.getElementById('close-modal').addEventListener('click', () => {
        document.getElementById('client-modal').classList.remove('active');
    });

    // Initial Load
    loadDashboardStats();
    loadData('dashboard');

    // Polling every 30s
    setInterval(() => {
        loadDashboardStats();
        const activeView = document.querySelector('.view.active').id;
        loadData(activeView);
    }, 30000);
});

// Utility formatting
function formatDate(isoString) {
    if (!isoString) return 'N/A';
    const d = new Date(isoString);
    return d.toLocaleString('en-US', { 
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

function formatCurrency(num) {
    if (!num) return 'N/A';
    return 'PKR ' + num.toLocaleString();
}

function getStatusClass(status) {
    status = String(status || '').toLowerCase();
    if (['success', 'booked', 'done'].includes(status)) return 'status-success';
    if (['failed', 'cancelled', 'error'].includes(status)) return 'status-danger';
    if (['pending', 'rescheduled'].includes(status)) return 'status-pending';
    return 'status-info';
}

// Data Fetching and Rendering
const apiBase = '/api/crm';

async function fetchAPI(endpoint) {
    try {
        const res = await fetch(`${apiBase}${endpoint}`);
        const data = await res.json();
        return data.success ? data : null;
    } catch (e) {
        console.error('API Error:', e);
        return null;
    }
}

async function loadDashboardStats() {
    const clientsData = await fetchAPI('/clients');
    const apptsData = await fetchAPI('/appointments');
    const eventsData = await fetchAPI('/events');
    const remsData = await fetchAPI('/reminders');

    if (clientsData) document.getElementById('stat-clients').textContent = clientsData.clients.length;
    if (apptsData) document.getElementById('stat-appointments').textContent = apptsData.appointments.length;
    
    if (eventsData) {
        document.getElementById('stat-events').textContent = eventsData.events.length;
        renderDashEvents(eventsData.events.slice(0, 5));
    }
    
    if (remsData) {
        const pending = remsData.reminders.filter(r => r.status === 'pending').length;
        document.getElementById('stat-reminders').textContent = pending;
    }
    
    if (apptsData) {
        renderDashAppointments(apptsData.appointments.slice(0, 5));
    }
}

function loadData(view, force = false) {
    switch (view) {
        case 'dashboard':
            // Handled by loadDashboardStats partially, but re-render widgets if needed
            loadDashboardStats();
            break;
        case 'clients':
            loadClients();
            break;
        case 'appointments':
            loadAppointments();
            break;
        case 'events':
            loadEvents();
            break;
        case 'reminders':
            loadReminders();
            break;
    }
}

// Renderers
async function loadClients() {
    const data = await fetchAPI('/clients');
    if (!data) return;
    
    const tbody = document.querySelector('#clients-table tbody');
    tbody.innerHTML = '';
    
    data.clients.forEach(c => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${c.client_phone}</strong></td>
            <td>${c.client_name || 'N/A'}</td>
            <td>${formatCurrency(c.budget)}</td>
            <td>${c.city || 'N/A'} ${c.area ? ' / ' + c.area : ''}</td>
            <td>${c.purpose || 'N/A'}</td>
            <td>${formatDate(c.updated_at)}</td>
            <td><button class="action-btn" onclick="showClientDetails('${c.client_phone}', '${c.client_name}')">View Details</button></td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadAppointments() {
    const data = await fetchAPI('/appointments');
    if (!data) return;
    
    const tbody = document.querySelector('#appointments-table tbody');
    tbody.innerHTML = '';
    
    data.appointments.forEach(a => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${a.client_name || 'Unknown'}</strong></td>
            <td>${a.client_phone || 'N/A'}</td>
            <td>${a.property_title || ('ID: ' + a.property_id)}</td>
            <td>${formatDate(a.start_datetime)}</td>
            <td><span class="status-badge ${getStatusClass(a.status)}">${a.status}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadEvents() {
    const data = await fetchAPI('/events');
    if (!data) return;
    
    const tbody = document.querySelector('#events-table tbody');
    tbody.innerHTML = '';
    
    data.events.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><small>${e.session_id.substring(0,8)}...</small></td>
            <td><strong>${e.event_type}</strong></td>
            <td><span class="status-badge ${getStatusClass(e.status)}">${e.status}</span></td>
            <td>${formatDate(e.created_at)}</td>
            <td><button class="action-btn" onclick="alert(JSON.stringify(${JSON.stringify(e.payload || {}).replace(/"/g, '&quot;')}, null, 2))">Payload</button></td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadReminders() {
    const data = await fetchAPI('/reminders');
    if (!data) return;
    
    const tbody = document.querySelector('#reminders-table tbody');
    tbody.innerHTML = '';
    
    data.reminders.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${r.client_name || 'Unknown'}</strong><br><small>${r.client_phone || 'N/A'}</small></td>
            <td>${r.reason}</td>
            <td>${formatDate(r.due_at)}</td>
            <td><span class="status-badge ${getStatusClass(r.status)}">${r.status}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

function renderDashAppointments(appts) {
    const tbody = document.querySelector('#dash-appointments-table tbody');
    tbody.innerHTML = '';
    appts.forEach(a => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${a.client_name || a.client_phone || 'Unknown'}</td>
            <td>${a.property_title || 'N/A'}</td>
            <td>${formatDate(a.start_datetime)}</td>
            <td><span class="status-badge ${getStatusClass(a.status)}">${a.status}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

function renderDashEvents(events) {
    const tbody = document.querySelector('#dash-events-table tbody');
    tbody.innerHTML = '';
    events.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${e.event_type}</td>
            <td><small>${formatDate(e.created_at)}</small></td>
            <td><span class="status-badge ${getStatusClass(e.status)}">${e.status}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

// Modal logic
window.showClientDetails = async function(phone, name) {
    const data = await fetchAPI(`/client/${encodeURIComponent(phone)}`);
    if (!data) return;
    
    document.getElementById('modal-client-name').textContent = `Details for ${name && name !== 'null' ? name : phone}`;
    
    const pref = data.preferences || {};
    const appts = data.appointments || [];
    
    const html = `
        <h3>Preferences</h3>
        <div class="detail-row"><div class="detail-label">Phone</div><div class="detail-value">${pref.client_phone || phone}</div></div>
        <div class="detail-row"><div class="detail-label">Budget</div><div class="detail-value">${formatCurrency(pref.budget)}</div></div>
        <div class="detail-row"><div class="detail-label">City</div><div class="detail-value">${pref.city || 'N/A'}</div></div>
        <div class="detail-row"><div class="detail-label">Area</div><div class="detail-value">${pref.area || 'N/A'}</div></div>
        <div class="detail-row"><div class="detail-label">Purpose</div><div class="detail-value">${pref.purpose || 'N/A'}</div></div>
        <div class="detail-row"><div class="detail-label">Bedrooms</div><div class="detail-value">${pref.bedrooms || 'Any'}</div></div>
        
        <h3 style="margin-top:24px;">Appointments (${appts.length})</h3>
        ${appts.map(a => `
            <div style="background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                <strong>${a.property_title}</strong> - <span class="status-badge ${getStatusClass(a.status)}">${a.status}</span><br>
                <small>${formatDate(a.start_datetime)}</small>
            </div>
        `).join('')}
    `;
    
    document.getElementById('modal-body').innerHTML = html;
    document.getElementById('client-modal').classList.add('active');
};
