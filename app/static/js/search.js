/**
 * Unified Search Page JavaScript
 */

// Global state
let currentQuery = '';
let currentPage = 1;
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
    // Search button
    searchBtn.addEventListener('click', () => {
        performSearch();
    });

    // Search input - trigger on Enter key
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
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

    if (!query) {
        showEmptyState();
        return;
    }

    if (query.length < 2) {
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

    try {
        const response = await fetch(`/search/api/search?${params.toString()}`);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.details || 'Search failed');
        }

        const data = await response.json();
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

    return `
        <div class="card mb-3 result-card">
            <div class="card-body">
                <div class="d-flex">
                    <div class="me-3">
                        <i class="bi ${icon} text-primary" style="font-size: 1.5rem;"></i>
                    </div>
                    <div class="flex-grow-1">
                        <h5 class="card-title mb-1">
                            <a href="${result.actions.view || '#'}" class="text-decoration-none">
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

    if (result.actions.view) {
        buttons.push(`<a href="${result.actions.view}" class="btn btn-outline-primary">
            <i class="bi bi-eye"></i> View
        </a>`);
    }

    if (result.actions.view_transcript) {
        buttons.push(`<a href="${result.actions.view_transcript}" class="btn btn-outline-secondary">
            <i class="bi bi-card-text"></i> Transcript
        </a>`);
    }

    if (result.actions.view_dashboard) {
        buttons.push(`<a href="${result.actions.view_dashboard}" class="btn btn-outline-secondary">
            <i class="bi bi-bar-chart"></i> Dashboard
        </a>`);
    }

    if (result.actions.view_results) {
        buttons.push(`<a href="${result.actions.view_results}" class="btn btn-outline-secondary">
            <i class="bi bi-file-text"></i> Results
        </a>`);
    }

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
    const date = new Date(timestamp);
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
