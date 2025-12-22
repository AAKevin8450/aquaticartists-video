/**
 * Unified Search Page JavaScript
 */

console.log('search.js loaded');

// Global state
let currentQuery = '';
let currentPage = 1;
let semanticEnabled = false;  // AI semantic search toggle
let currentFilters = {
    sources: ['file', 'transcript', 'rekognition', 'nova', 'collection'],
    file_type: '',
    from_date: '',
    to_date: '',
    status: '',
    analysis_type: '',
    model: '',
    sort_by: 'relevance',
    sort_order: 'desc'
};
let searchDebounceTimer = null;
let lastSearchResults = null;

// DOM Elements
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const clearSearchBtn = document.getElementById('clearSearchBtn');
const resetFiltersBtn = document.getElementById('resetFiltersBtn');
const semanticToggle = document.getElementById('semanticToggle');
const resultsSection = document.getElementById('resultsSection');
const resultsContainer = document.getElementById('resultsContainer');
const resultsCount = document.getElementById('resultsCount');
const resultsBreakdown = document.getElementById('resultsBreakdown');
const searchTime = document.getElementById('searchTime');
const paginationContainer = document.getElementById('paginationContainer');
const pagination = document.getElementById('pagination');
const emptyState = document.getElementById('emptyState');
const noResultsState = document.getElementById('noResultsState');
const loadingState = document.getElementById('loadingState');
const errorState = document.getElementById('errorState');

// Source type icon mapping
const sourceIcons = {
    file: 'bi-file-earmark',
    transcript: 'bi-card-text',
    rekognition: 'bi-eye',
    nova: 'bi-stars',
    face_collection: 'bi-people'
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOMContentLoaded fired');
    console.log('searchInput element:', searchInput);
    console.log('searchBtn element:', searchBtn);

    initializeFilters();
    setupEventListeners();
    setupKeyboardShortcuts();
    loadFiltersFromURL();

    // Load available filter options from API
    loadFilterOptions();
});

/**
 * Initialize filter controls
 */
function initializeFilters() {
    // Set up source checkboxes
    document.querySelectorAll('.source-filter').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            updateSourceFilters();
            if (currentQuery) {
                performSearch();
            }
        });
    });

    // Set up other filter controls
    document.getElementById('fileTypeFilter').addEventListener('change', (e) => {
        currentFilters.file_type = e.target.value;
        if (currentQuery) performSearch();
    });

    document.getElementById('statusFilter').addEventListener('change', (e) => {
        currentFilters.status = e.target.value;
        if (currentQuery) performSearch();
    });

    document.getElementById('modelFilter').addEventListener('change', (e) => {
        currentFilters.model = e.target.value;
        if (currentQuery) performSearch();
    });

    document.getElementById('analysisTypeFilter').addEventListener('change', (e) => {
        currentFilters.analysis_type = e.target.value;
        if (currentQuery) performSearch();
    });

    document.getElementById('fromDateFilter').addEventListener('change', (e) => {
        currentFilters.from_date = e.target.value;
        if (currentQuery) performSearch();
    });

    document.getElementById('toDateFilter').addEventListener('change', (e) => {
        currentFilters.to_date = e.target.value;
        if (currentQuery) performSearch();
    });

    // Sort options
    document.querySelectorAll('input[name="sortBy"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            currentFilters.sort_by = e.target.value;
            if (currentQuery) performSearch();
        });
    });

    document.querySelectorAll('input[name="sortOrder"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            currentFilters.sort_order = e.target.value;
            if (currentQuery) performSearch();
        });
    });
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    console.log('setupEventListeners called');

    // Search button
    searchBtn.addEventListener('click', () => {
        console.log('Search button clicked');
        performSearch();
    });

    // Search input - trigger on Enter key
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            console.log('Enter key pressed in search input');
            performSearch();
        }
    });

    // Clear search button
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        currentQuery = '';
        hideResults();
        showEmptyState();
    });

    // Semantic search toggle
    if (semanticToggle) {
        semanticToggle.addEventListener('change', (e) => {
            semanticEnabled = e.target.checked;
            console.log('Semantic search toggled:', semanticEnabled);
            // Re-run search if there's an active query
            if (currentQuery) {
                performSearch();
            }
        });
    }

    // Show/hide clear button based on input
    searchInput.addEventListener('input', (e) => {
        if (e.target.value) {
            clearSearchBtn.style.display = 'block';
        } else {
            clearSearchBtn.style.display = 'none';
        }
    });

    // Reset filters button
    resetFiltersBtn.addEventListener('click', () => {
        resetFilters();
    });
}

/**
 * Setup keyboard shortcuts
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+K or Cmd+K to focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            searchInput.focus();
        }

        // Escape to clear search
        if (e.key === 'Escape' && document.activeElement === searchInput) {
            searchInput.blur();
        }
    });
}

/**
 * Update source filters from checkboxes
 */
function updateSourceFilters() {
    const sources = [];
    document.querySelectorAll('.source-filter:checked').forEach(checkbox => {
        sources.push(checkbox.value);
    });
    currentFilters.sources = sources;
}

/**
 * Reset all filters to default
 */
function resetFilters() {
    // Reset checkboxes
    document.querySelectorAll('.source-filter').forEach(checkbox => {
        checkbox.checked = true;
    });

    // Reset selects
    document.getElementById('fileTypeFilter').value = '';
    document.getElementById('statusFilter').value = '';
    document.getElementById('modelFilter').value = '';
    document.getElementById('analysisTypeFilter').value = '';
    document.getElementById('fromDateFilter').value = '';
    document.getElementById('toDateFilter').value = '';

    // Reset radio buttons
    document.getElementById('sortRelevance').checked = true;
    document.getElementById('sortDesc').checked = true;

    // Reset state
    currentFilters = {
        sources: ['file', 'transcript', 'rekognition', 'nova', 'collection'],
        file_type: '',
        from_date: '',
        to_date: '',
        status: '',
        analysis_type: '',
        model: '',
        sort_by: 'relevance',
        sort_order: 'desc'
    };

    // Re-run search if there's a query
    if (currentQuery) {
        performSearch();
    }
}

/**
 * Load filter options from API
 */
async function loadFilterOptions() {
    try {
        const response = await fetch('/search/api/search/filters');
        if (!response.ok) throw new Error('Failed to load filters');

        const data = await response.json();

        // Populate analysis types
        const analysisTypeSelect = document.getElementById('analysisTypeFilter');
        data.analysis_types.forEach(type => {
            const option = document.createElement('option');
            option.value = type;
            option.textContent = formatAnalysisType(type);
            analysisTypeSelect.appendChild(option);
        });

        // Populate Whisper models
        const whisperGroup = document.getElementById('whisperModels');
        data.models.whisper.forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            whisperGroup.appendChild(option);
        });

        // Populate Nova models
        const novaGroup = document.getElementById('novaModels');
        data.models.nova.forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            novaGroup.appendChild(option);
        });

    } catch (error) {
        console.error('Error loading filter options:', error);
    }
}

/**
 * Perform search with current query and filters
 */
async function performSearch(page = 1) {
    const query = searchInput.value.trim();

    console.log('performSearch called with query:', query);

    if (!query) {
        console.log('Empty query, showing empty state');
        showEmptyState();
        return;
    }

    if (query.length < 2) {
        console.log('Query too short:', query);
        showError('Search query must be at least 2 characters');
        return;
    }

    currentQuery = query;
    currentPage = page;

    // Show loading state
    showLoadingState();

    // Build query parameters
    const params = new URLSearchParams();
    params.append('q', query);
    params.append('page', page);
    params.append('per_page', 50);
    params.append('semantic', semanticEnabled ? 'true' : 'false');

    // Add filters
    if (currentFilters.sources && currentFilters.sources.length > 0) {
        params.append('sources', currentFilters.sources.join(','));
    }
    if (currentFilters.file_type) params.append('file_type', currentFilters.file_type);
    if (currentFilters.from_date) params.append('from_date', currentFilters.from_date);
    if (currentFilters.to_date) params.append('to_date', currentFilters.to_date);
    if (currentFilters.status) params.append('status', currentFilters.status);
    if (currentFilters.analysis_type) params.append('analysis_type', currentFilters.analysis_type);
    if (currentFilters.model) params.append('model', currentFilters.model);
    if (currentFilters.sort_by) params.append('sort_by', currentFilters.sort_by);
    if (currentFilters.sort_order) params.append('sort_order', currentFilters.sort_order);

    const url = `/search/api/search?${params.toString()}`;
    console.log('Fetching search results from:', url);

    try {
        const response = await fetch(url);
        console.log('Response status:', response.status, response.statusText);

        if (!response.ok) {
            const error = await response.json();
            console.error('Server error response:', error);
            throw new Error(error.details || 'Search failed');
        }

        const data = await response.json();
        console.log('Search results:', data);
        lastSearchResults = data;

        // Display results
        displayResults(data);

        // Update URL
        updateURL(params);

    } catch (error) {
        console.error('Search error:', error);
        showError(error.message);
    }
}

/**
 * Display search results
 */
function displayResults(data) {
    // Hide states
    hideAllStates();

    // Show results section
    resultsSection.style.display = 'block';

    // Update results count
    resultsCount.innerHTML = `
        <strong>${data.total_results.toLocaleString()}</strong> result${data.total_results !== 1 ? 's' : ''}
        ${data.total_results > 0 ? `for "<span class="text-primary">${escapeHtml(data.query)}</span>"` : ''}
    `;

    // Update breakdown
    const breakdown = [];
    if (data.results_by_source.file > 0) breakdown.push(`Files: ${data.results_by_source.file}`);
    if (data.results_by_source.transcript > 0) breakdown.push(`Transcripts: ${data.results_by_source.transcript}`);
    if (data.results_by_source.rekognition > 0) breakdown.push(`Rekognition: ${data.results_by_source.rekognition}`);
    if (data.results_by_source.nova > 0) breakdown.push(`Nova: ${data.results_by_source.nova}`);
    if (data.results_by_source.collection > 0) breakdown.push(`Collections: ${data.results_by_source.collection}`);
    resultsBreakdown.textContent = breakdown.join(' • ');

    // Update search time
    searchTime.textContent = `${data.search_time_ms}ms`;

    // Check if no results
    if (data.total_results === 0) {
        resultsContainer.innerHTML = '';
        showNoResults(data.query);
        return;
    }

    // Render results
    resultsContainer.innerHTML = data.results.map(result => renderResult(result, data.query)).join('');

    // Render pagination
    renderPagination(data.pagination);
}

/**
 * Get onclick handler for result title
 */
function getTitleOnClick(result) {
    const sourceType = result.source_type;
    const sourceId = result.source_id;

    if (sourceType === 'file') {
        return `viewFileDetails(${sourceId})`;
    } else if (sourceType === 'transcript') {
        return `openTranscriptDetails(${sourceId})`;
    } else if (sourceType === 'rekognition') {
        return `viewAnalysisResult(${sourceId}, 'rekognition')`;
    } else if (sourceType === 'nova') {
        return `viewAnalysisResult(${sourceId}, 'nova')`;
    } else if (sourceType === 'face_collection') {
        return `window.location.href='/collections?id=${sourceId}'`;
    }
    return '';
}

/**
 * Render a single search result
 */
function renderResult(result, query) {
    const icon = sourceIcons[result.source_type] || 'bi-file-earmark';
    const preview = highlightText(result.preview, query);

    // Format timestamp
    const timestamp = result.timestamp ? formatTimestamp(result.timestamp) : '';

    // Build action buttons
    const actions = buildActionButtons(result);

    // Metadata badges
    const metadata = buildMetadataBadges(result);

    // Generate onclick handler for title
    const titleOnClick = getTitleOnClick(result);

    return `
        <div class="card mb-3 result-card">
            <div class="card-body">
                <div class="d-flex">
                    <div class="me-3">
                        <i class="bi ${icon} text-primary" style="font-size: 1.5rem;"></i>
                    </div>
                    <div class="flex-grow-1">
                        <h5 class="card-title mb-1">
                            <a href="#" class="text-decoration-none" onclick="${titleOnClick}; return false;" style="cursor: pointer;">
                                ${escapeHtml(result.title)}
                            </a>
                        </h5>
                        <p class="text-muted small mb-2">
                            <span class="badge bg-secondary me-2">${result.category}</span>
                            ${timestamp ? `<span class="me-2"><i class="bi bi-clock"></i> ${timestamp}</span>` : ''}
                            ${metadata}
                        </p>
                        <p class="card-text">${preview}</p>
                        <div class="btn-group btn-group-sm" role="group">
                            ${actions}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Build action buttons for a result
 */
function buildActionButtons(result) {
    const buttons = [];
    const sourceType = result.source_type;
    const sourceId = result.source_id;

    // Main "View" button - opens modal on search page
    if (sourceType === 'file') {
        buttons.push(`<button class="btn btn-outline-primary" onclick="viewFileDetails(${sourceId})">
            <i class="bi bi-eye"></i> View Details
        </button>`);
    } else if (sourceType === 'transcript') {
        buttons.push(`<button class="btn btn-outline-primary" onclick="openTranscriptDetails(${sourceId})">
            <i class="bi bi-eye"></i> View Transcript
        </button>`);
    } else if (sourceType === 'rekognition') {
        // For Rekognition, we need to get the file_id first
        buttons.push(`<button class="btn btn-outline-primary" onclick="viewAnalysisResult(${sourceId}, 'rekognition')">
            <i class="bi bi-eye"></i> View Analysis
        </button>`);
    } else if (sourceType === 'nova') {
        buttons.push(`<button class="btn btn-outline-primary" onclick="viewAnalysisResult(${sourceId}, 'nova')">
            <i class="bi bi-stars"></i> View Analysis
        </button>`);
    } else if (sourceType === 'face_collection') {
        // Collections navigate to collections page (external)
        buttons.push(`<a href="/collections?id=${sourceId}" class="btn btn-outline-primary">
            <i class="bi bi-people"></i> View Collection
        </a>`);
    }

    // Dashboard link (opens in new tab for Rekognition results)
    if (result.actions.view_dashboard) {
        buttons.push(`<a href="${result.actions.view_dashboard}" class="btn btn-outline-secondary" target="_blank">
            <i class="bi bi-bar-chart"></i> Dashboard
        </a>`);
    }

    // Download button
    if (result.actions.download) {
        buttons.push(`<a href="${result.actions.download}" class="btn btn-outline-success">
            <i class="bi bi-download"></i> Download
        </a>`);
    }

    return buttons.join('');
}

/**
 * Build metadata badges for a result
 */
function buildMetadataBadges(result) {
    const badges = [];

    if (result.metadata.size_bytes) {
        badges.push(`<span class="me-2"><i class="bi bi-hdd"></i> ${formatFileSize(result.metadata.size_bytes)}</span>`);
    }

    if (result.metadata.duration_seconds) {
        badges.push(`<span class="me-2"><i class="bi bi-clock-history"></i> ${formatDuration(result.metadata.duration_seconds)}</span>`);
    }

    return badges.join('');
}

/**
 * Render pagination controls
 */
function renderPagination(paginationData) {
    if (paginationData.pages <= 1) {
        paginationContainer.style.display = 'none';
        return;
    }

    paginationContainer.style.display = 'block';

    const currentPage = paginationData.page;
    const totalPages = paginationData.pages;

    let paginationHTML = '';

    // Previous button
    paginationHTML += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="performSearch(${currentPage - 1}); return false;">
                <i class="bi bi-chevron-left"></i> Previous
            </a>
        </li>
    `;

    // Page numbers (show max 5 pages)
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);

    for (let i = startPage; i <= endPage; i++) {
        paginationHTML += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="performSearch(${i}); return false;">${i}</a>
            </li>
        `;
    }

    // Next button
    paginationHTML += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="performSearch(${currentPage + 1}); return false;">
                Next <i class="bi bi-chevron-right"></i>
            </a>
        </li>
    `;

    pagination.innerHTML = paginationHTML;
}

/**
 * Highlight search term in text
 */
function highlightText(text, query) {
    if (!text || !query) return escapeHtml(text);

    const escapedText = escapeHtml(text);
    const escapedQuery = escapeRegex(query);
    const regex = new RegExp(`(${escapedQuery})`, 'gi');

    return escapedText.replace(regex, '<mark>$1</mark>');
}

/**
 * Show/hide states
 */
function showLoadingState() {
    hideAllStates();
    loadingState.style.display = 'block';
}

function showEmptyState() {
    hideAllStates();
    emptyState.style.display = 'block';
}

function showNoResults(query) {
    hideAllStates();
    noResultsState.style.display = 'block';
    document.getElementById('noResultsMessage').textContent =
        `No results found for "${query}". Try different keywords or adjust your filters.`;
}

function showError(message) {
    hideAllStates();
    errorState.style.display = 'block';
    document.getElementById('errorMessage').textContent = message;
}

function hideResults() {
    resultsSection.style.display = 'none';
}

function hideAllStates() {
    emptyState.style.display = 'none';
    noResultsState.style.display = 'none';
    loadingState.style.display = 'none';
    errorState.style.display = 'none';
    resultsSection.style.display = 'none';
}

/**
 * URL management
 */
function updateURL(params) {
    const newURL = `${window.location.pathname}?${params.toString()}`;
    window.history.pushState({}, '', newURL);
}

function loadFiltersFromURL() {
    const params = new URLSearchParams(window.location.search);
    const query = params.get('q');

    if (query) {
        searchInput.value = query;
        clearSearchBtn.style.display = 'block';

        // Load other filters from URL
        if (params.has('sources')) {
            const sources = params.get('sources').split(',');
            document.querySelectorAll('.source-filter').forEach(checkbox => {
                checkbox.checked = sources.includes(checkbox.value);
            });
            updateSourceFilters();
        }

        // Trigger search
        performSearch();
    }
}

/**
 * Utility functions
 */
function formatAnalysisType(type) {
    return type.split('_').map(word =>
        word.charAt(0).toUpperCase() + word.slice(1)
    ).join(' ');
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';

    if (typeof timestamp === 'number') {
        const ms = timestamp > 1e12 ? timestamp : timestamp * 1000;
        const date = new Date(ms);
        if (!Number.isNaN(date.getTime())) {
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit'
            });
        }
    }

    const raw = String(timestamp).trim();
    if (!raw) return 'N/A';

    if (/\\b(ET|EST|EDT|UTC|GMT)\\b/.test(raw)) {
        return raw;
    }

    let parsed = Date.parse(raw);
    if (Number.isNaN(parsed)) {
        parsed = Date.parse(raw.replace(' ', 'T'));
    }

    if (Number.isNaN(parsed)) {
        return raw;
    }

    const date = new Date(parsed);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Make performSearch available globally for pagination
window.performSearch = performSearch;

// ============================================================================
// MODAL FUNCTIONS
// ============================================================================

async function viewFileDetails(fileId) {
    const modal = new bootstrap.Modal(document.getElementById('fileDetailsModal'));
    const modalBody = document.getElementById('fileDetailsBody');

    modalBody.innerHTML = '<div class="text-center"><div class="spinner-border"></div></div>';
    modal.show();

    try {
        const response = await fetch(`/api/files/${fileId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load file details');
        }

        const data = await response.json();
        renderFileDetails(data, modalBody);

    } catch (error) {
        console.error('Failed to load file details:', error);
        modalBody.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Failed to load file details: ${error.message}
            </div>
        `;
    }
}

function renderFileDetails(data, container) {
    const { file, proxy, analysis_jobs, transcripts } = data;
    const media = file.media_metadata || {};

    let html = `
        <div class="row g-3">
            <div class="col-md-6">
                <h6><i class="bi bi-file-earmark"></i> File Information</h6>
                <table class="table table-sm">
                    <tr><th>Filename:</th><td>${escapeHtml(file.filename || 'N/A')}</td></tr>
                    <tr><th>Type:</th><td>${escapeHtml(file.file_type || 'N/A')}</td></tr>
                    <tr><th>Size:</th><td>${formatFileSize(file.size_bytes || 0)}</td></tr>
                    <tr><th>Duration:</th><td>${formatDuration(media.duration_seconds || 0)}</td></tr>
                    <tr><th>Uploaded:</th><td>${formatTimestamp(file.uploaded_at)}</td></tr>
                </table>
            </div>
            <div class="col-md-6">
                <h6><i class="bi bi-gear"></i> Technical Details</h6>
                <table class="table table-sm">
                    <tr><th>Resolution:</th><td>${media.resolution_width || 'N/A'} × ${media.resolution_height || 'N/A'}</td></tr>
                    <tr><th>Frame Rate:</th><td>${media.frame_rate || 'N/A'} fps</td></tr>
                    <tr><th>Video Codec:</th><td>${escapeHtml(media.codec_video || 'N/A')}</td></tr>
                    <tr><th>Audio Codec:</th><td>${escapeHtml(media.codec_audio || 'N/A')}</td></tr>
                    <tr><th>Bitrate:</th><td>${media.bitrate ? (media.bitrate / 1000).toFixed(0) + ' kbps' : 'N/A'}</td></tr>
                </table>
            </div>
        </div>
    `;

    // Proxy information
    if (proxy) {
        html += `
            <div class="mt-3">
                <h6><i class="bi bi-film"></i> Proxy File</h6>
                <table class="table table-sm">
                    <tr><th>Filename:</th><td>${escapeHtml(proxy.filename || 'N/A')}</td></tr>
                    <tr><th>Size:</th><td>${formatFileSize(proxy.size_bytes || 0)}</td></tr>
                    <tr><th>Created:</th><td>${formatTimestamp(proxy.uploaded_at)}</td></tr>
                </table>
            </div>
        `;
    }

    // Transcripts
    if (transcripts && transcripts.length > 0) {
        html += `
            <div class="mt-3">
                <h6><i class="bi bi-card-text"></i> Transcripts (${transcripts.length})</h6>
                <div class="list-group">
        `;
        transcripts.forEach(t => {
            const statusBadge = getStatusBadgeClass(t.status);
            html += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${escapeHtml(t.model_name || 'N/A')}</strong>
                            <span class="badge bg-${statusBadge} ms-2">${t.status}</span>
                            <br>
                            <small class="text-muted">${formatTimestamp(t.created_at)}</small>
                        </div>
                        <button class="btn btn-sm btn-primary" onclick="openTranscriptDetails(${t.id})">
                            <i class="bi bi-eye"></i> View
                        </button>
                    </div>
                </div>
            `;
        });
        html += `</div></div>`;
    }

    // Analysis jobs
    if (analysis_jobs && analysis_jobs.length > 0) {
        html += `
            <div class="mt-3">
                <h6><i class="bi bi-eye"></i> Analysis Jobs (${analysis_jobs.length})</h6>
                <div class="list-group">
        `;
        analysis_jobs.forEach(job => {
            const statusBadge = getStatusBadgeClass(job.status);
            html += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${escapeHtml(job.analysis_type || 'N/A')}</strong>
                            <span class="badge bg-${statusBadge} ms-2">${job.status}</span>
                            <br>
                            <small class="text-muted">${formatTimestamp(job.started_at || job.completed_at)}</small>
                        </div>
                        ${job.status === 'SUCCEEDED' ? `
                            <a href="/dashboard/${job.id}" class="btn btn-sm btn-primary" target="_blank">
                                <i class="bi bi-bar-chart"></i> Dashboard
                            </a>
                        ` : ''}
                    </div>
                </div>
            `;
        });
        html += `</div></div>`;
    }

    container.innerHTML = html;
}

async function openTranscriptDetails(transcriptId) {
    const modalEl = document.getElementById('transcriptDetailsModal');
    const modalBody = document.getElementById('transcriptDetailsBody');
    if (!modalEl || !modalBody) {
        showError('Transcript details modal not available.');
        return;
    }

    const modal = new bootstrap.Modal(modalEl);
    modalBody.innerHTML = '<div class="text-center"><div class="spinner-border"></div></div>';
    modal.show();

    try {
        const response = await fetch(`/transcriptions/api/transcript/${transcriptId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load transcript');
        }

        const transcript = await response.json();
        const statusClass = `bg-${getStatusBadgeClass(transcript.status)}`;
        const transcriptText = transcript.transcript_text ? escapeHtml(transcript.transcript_text) : '';

        modalBody.innerHTML = `
            <div class="mb-3">
                <h6 class="mb-1"><i class="bi bi-file-earmark-play"></i> ${escapeHtml(transcript.file_name || 'Unknown file')}</h6>
                <p class="text-muted small mb-2">${escapeHtml(transcript.file_path || 'N/A')}</p>
                <div class="row g-2">
                    <div class="col-md-3">
                        <strong>Status:</strong> <span class="badge ${statusClass}">${transcript.status || 'N/A'}</span>
                    </div>
                    <div class="col-md-3">
                        <strong>Model:</strong> ${escapeHtml(transcript.model_name || 'N/A')}
                    </div>
                    <div class="col-md-3">
                        <strong>Language:</strong> ${escapeHtml(transcript.language || 'N/A')}
                    </div>
                    <div class="col-md-3">
                        <strong>Duration:</strong> ${formatDuration(transcript.duration_seconds || 0)}
                    </div>
                </div>
                <div class="row g-2 mt-2">
                    <div class="col-md-3">
                        <strong>Words:</strong> ${(transcript.word_count || 0).toLocaleString()}
                    </div>
                    <div class="col-md-3">
                        <strong>Created:</strong> ${formatTimestamp(transcript.created_at)}
                    </div>
                    <div class="col-md-6">
                        <a href="/transcriptions/api/transcript/${transcriptId}/download?format=txt" class="btn btn-sm btn-success">
                            <i class="bi bi-download"></i> Download TXT
                        </a>
                        <a href="/transcriptions/api/transcript/${transcriptId}/download?format=srt" class="btn btn-sm btn-success">
                            <i class="bi bi-download"></i> Download SRT
                        </a>
                    </div>
                </div>
            </div>
            <div class="mt-3">
                <h6>Transcript Text</h6>
                <div class="border rounded p-3" style="max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; background-color: #f8f9fa;">
${transcriptText || 'No transcript text available'}
                </div>
            </div>
        `;

    } catch (error) {
        console.error('Failed to load transcript:', error);
        modalBody.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Failed to load transcript: ${error.message}
            </div>
        `;
    }
}

function getStatusBadgeClass(status) {
    const statusMap = {
        'SUCCEEDED': 'success',
        'COMPLETED': 'success',
        'FAILED': 'danger',
        'IN_PROGRESS': 'warning',
        'SUBMITTED': 'info',
        'PENDING': 'secondary'
    };
    return statusMap[status] || 'secondary';
}

async function viewAnalysisResult(jobId, type) {
    try {
        if (type === 'rekognition') {
            // Get job details to find the file_id
            const response = await fetch(`/api/history/${jobId}`);
            if (!response.ok) {
                throw new Error('Failed to load job details');
            }
            const job = await response.json();
            if (job.file_id) {
                viewFileDetails(job.file_id);
            } else {
                showError('Could not find file for this analysis job');
            }
        } else if (type === 'nova') {
            // Get Nova job details to find the file_id
            const response = await fetch(`/api/nova/results/${jobId}`);
            if (!response.ok) {
                throw new Error('Failed to load Nova job details');
            }
            const novaJob = await response.json();
            if (novaJob.analysis_job_id) {
                const jobResponse = await fetch(`/api/history/${novaJob.analysis_job_id}`);
                if (!jobResponse.ok) {
                    throw new Error('Failed to load analysis job details');
                }
                const job = await jobResponse.json();
                if (job.file_id) {
                    viewFileDetails(job.file_id);
                } else {
                    showError('Could not find file for this Nova analysis');
                }
            } else {
                showError('Could not find file for this Nova analysis');
            }
        }
    } catch (error) {
        console.error('Failed to view analysis:', error);
        showError(`Failed to open analysis: ${error.message}`);
    }
}

// Make modal functions available globally
window.viewFileDetails = viewFileDetails;
window.openTranscriptDetails = openTranscriptDetails;
window.viewAnalysisResult = viewAnalysisResult;
