import { showAlert } from './utils.js';

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

let currentFilters = {
    search: '',
    file_type: '',
    has_proxy: null,
    has_transcription: null,
    from_date: '',
    to_date: '',
    sort_by: 'uploaded_at',
    sort_order: 'desc',
    page: 1,
    per_page: 50
};

let currentFiles = [];
let currentPagination = null;
let s3FilesLoaded = false;

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    loadFiles();
});

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function initializeEventListeners() {
    // Search input (debounced)
    const searchInput = document.getElementById('searchInput');
    let searchDebounceTimer = null;

    searchInput.addEventListener('input', (e) => {
        if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            currentFilters.search = e.target.value;
            currentFilters.page = 1;
            loadFiles();
        }, 300);
    });

    // Clear search
    document.getElementById('clearSearchBtn').addEventListener('click', () => {
        searchInput.value = '';
        currentFilters.search = '';
        currentFilters.page = 1;
        loadFiles();
    });

    // Apply filters
    document.getElementById('applyFiltersBtn').addEventListener('click', applyFilters);

    // Reset filters
    document.getElementById('resetFiltersBtn').addEventListener('click', resetFilters);

    // S3 files section (lazy load)
    const s3FilesCollapse = document.getElementById('s3FilesCollapse');
    s3FilesCollapse.addEventListener('show.bs.collapse', () => {
        if (!s3FilesLoaded) {
            loadS3Files();
        }
    });
}

function applyFilters() {
    currentFilters.file_type = document.getElementById('fileTypeFilter').value;

    const proxyFilter = document.getElementById('proxyFilter').value;
    currentFilters.has_proxy = proxyFilter === '' ? null : proxyFilter === 'true';

    const transcriptionFilter = document.getElementById('transcriptionFilter').value;
    currentFilters.has_transcription = transcriptionFilter === '' ? null : transcriptionFilter === 'true';

    currentFilters.from_date = document.getElementById('fromDate').value;
    currentFilters.to_date = document.getElementById('toDate').value;

    currentFilters.page = 1;
    loadFiles();
}

function resetFilters() {
    // Reset filter values
    document.getElementById('searchInput').value = '';
    document.getElementById('fileTypeFilter').value = '';
    document.getElementById('proxyFilter').value = '';
    document.getElementById('transcriptionFilter').value = '';
    document.getElementById('fromDate').value = '';
    document.getElementById('toDate').value = '';

    // Reset state
    currentFilters = {
        search: '',
        file_type: '',
        has_proxy: null,
        has_transcription: null,
        from_date: '',
        to_date: '',
        sort_by: 'uploaded_at',
        sort_order: 'desc',
        page: 1,
        per_page: 50
    };

    loadFiles();
}

// ============================================================================
// FILE LOADING
// ============================================================================

async function loadFiles() {
    const container = document.getElementById('filesContainer');
    container.innerHTML = '<div class="text-center"><div class="spinner-border"></div></div>';

    try {
        // Build query string
        const params = new URLSearchParams();
        Object.keys(currentFilters).forEach(key => {
            const value = currentFilters[key];
            if (value !== '' && value !== null && value !== undefined) {
                params.append(key, value);
            }
        });

        const response = await fetch(`/api/files?${params.toString()}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load files');
        }

        const data = await response.json();
        currentFiles = data.files;
        currentPagination = data.pagination;

        renderFiles(currentFiles);
        renderPagination(currentPagination);
        updateFilesCount(currentPagination.total);

    } catch (error) {
        console.error('Failed to load files:', error);
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Failed to load files: ${error.message}
            </div>
        `;
    }
}

// ============================================================================
// FILE RENDERING
// ============================================================================

function renderFiles(files) {
    const container = document.getElementById('filesContainer');

    if (files.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-5">
                <i class="bi bi-inbox fs-1"></i>
                <p class="mt-3">No files found</p>
                <a href="/upload" class="btn btn-primary">
                    <i class="bi bi-cloud-upload"></i> Upload Files
                </a>
            </div>
        `;
        return;
    }

    const table = `
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th style="width: 30%">File</th>
                        <th style="width: 8%">Type</th>
                        <th style="width: 10%">Size</th>
                        <th style="width: 10%">Duration</th>
                        <th style="width: 12%">Resolution</th>
                        <th style="width: 15%">Status</th>
                        <th style="width: 10%">Uploaded</th>
                        <th style="width: 15%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${files.map(renderFileRow).join('')}
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = table;
    attachFileEventListeners();
}

function renderFileRow(file) {
    const fileIcon = file.file_type === 'video' ? 'file-earmark-play' : 'file-earmark-image';
    const typeBadgeColor = file.file_type === 'video' ? 'primary' : 'success';

    // Build codec info string
    let codecInfo = '';
    if (file.resolution) {
        codecInfo += file.resolution;
    }
    if (file.codec_video) {
        codecInfo += ` • ${file.codec_video}`;
        if (file.codec_audio) {
            codecInfo += `/${file.codec_audio}`;
        }
    }
    if (file.frame_rate) {
        codecInfo += ` • ${file.frame_rate.toFixed(1)}fps`;
    }

    // Status badges
    const statusBadges = [];
    if (file.has_proxy) {
        statusBadges.push('<span class="badge bg-success" title="Proxy available on S3"><i class="bi bi-cloud-check"></i> Proxy</span>');
    }
    if (file.completed_transcripts > 0) {
        statusBadges.push(`<span class="badge bg-info" title="${file.completed_transcripts} completed transcripts"><i class="bi bi-mic"></i> ${file.completed_transcripts}</span>`);
    }
    if (file.total_analyses > 0) {
        const badgeClass = file.running_analyses > 0 ? 'bg-warning' : 'bg-primary';
        const icon = file.running_analyses > 0 ? 'hourglass-split' : 'graph-up';
        statusBadges.push(`<span class="badge ${badgeClass}" title="${file.completed_analyses}/${file.total_analyses} analyses"><i class="bi bi-${icon}"></i> ${file.completed_analyses}/${file.total_analyses}</span>`);
    }

    return `
        <tr data-file-id="${file.id}">
            <td>
                <div class="d-flex align-items-start gap-2">
                    <i class="bi bi-${fileIcon} fs-4 text-${typeBadgeColor}"></i>
                    <div class="flex-grow-1" style="min-width: 0;">
                        <div class="fw-semibold text-truncate" style="max-width: 300px;" title="${escapeHtml(file.filename)}">
                            ${escapeHtml(file.filename)}
                        </div>
                        ${codecInfo ? `<small class="text-muted">${codecInfo}</small>` : ''}
                    </div>
                </div>
            </td>
            <td>
                <span class="badge bg-${typeBadgeColor}">
                    ${file.file_type}
                </span>
            </td>
            <td>${file.size_display}</td>
            <td>${file.duration_display || 'N/A'}</td>
            <td>${file.resolution || 'N/A'}</td>
            <td>
                <div class="d-flex flex-wrap gap-1">
                    ${statusBadges.join('')}
                    ${statusBadges.length === 0 ? '<span class="text-muted small">No processing</span>' : ''}
                </div>
            </td>
            <td>${file.uploaded_at}</td>
            <td>
                ${renderActionsDropdown(file)}
            </td>
        </tr>
    `;
}

function renderActionsDropdown(file) {
    return `
        <div class="btn-group" role="group">
            <button class="btn btn-sm btn-primary view-details-btn"
                    data-file-id="${file.id}">
                <i class="bi bi-eye"></i>
            </button>
            <button type="button" class="btn btn-sm btn-primary dropdown-toggle dropdown-toggle-split"
                    data-bs-toggle="dropdown">
                <span class="visually-hidden">Toggle Dropdown</span>
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
                <li><h6 class="dropdown-header">Quick Actions</h6></li>
                ${!file.has_proxy && file.file_type === 'video' ? `
                    <li>
                        <a class="dropdown-item action-create-proxy" href="#" data-file-id="${file.id}">
                            <i class="bi bi-badge-hd"></i> Create Proxy
                        </a>
                    </li>
                ` : ''}
                <li>
                    <a class="dropdown-item action-transcribe" href="#" data-file-id="${file.id}">
                        <i class="bi bi-mic"></i> Transcribe
                    </a>
                </li>
                <li><hr class="dropdown-divider"></li>
                <li><h6 class="dropdown-header">Analysis</h6></li>
                <li>
                    <a class="dropdown-item action-analyze-rekognition" href="#" data-file-id="${file.id}">
                        <i class="bi bi-eye"></i> Rekognition
                    </a>
                </li>
                ${file.file_type === 'video' ? `
                    <li>
                        <a class="dropdown-item action-analyze-nova" href="#" data-file-id="${file.id}">
                            <i class="bi bi-stars"></i> Nova
                        </a>
                    </li>
                ` : ''}
                <li><hr class="dropdown-divider"></li>
                <li>
                    <a class="dropdown-item action-download" href="#" data-file-id="${file.id}">
                        <i class="bi bi-download"></i> Download
                    </a>
                </li>
                <li>
                    <a class="dropdown-item text-danger action-delete" href="#" data-file-id="${file.id}">
                        <i class="bi bi-trash"></i> Delete
                    </a>
                </li>
            </ul>
        </div>
    `;
}

function attachFileEventListeners() {
    // View details buttons
    document.querySelectorAll('.view-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            viewFileDetails(fileId);
        });
    });

    // Create proxy
    document.querySelectorAll('.action-create-proxy').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            createProxy(fileId);
        });
    });

    // Transcribe
    document.querySelectorAll('.action-transcribe').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startTranscription(fileId);
        });
    });

    // Rekognition analysis
    document.querySelectorAll('.action-analyze-rekognition').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startRekognitionAnalysis(fileId);
        });
    });

    // Nova analysis
    document.querySelectorAll('.action-analyze-nova').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startNovaAnalysis(fileId);
        });
    });

    // Download
    document.querySelectorAll('.action-download').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            downloadFile(fileId);
        });
    });

    // Delete
    document.querySelectorAll('.action-delete').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            deleteFile(fileId);
        });
    });
}

// ============================================================================
// PAGINATION
// ============================================================================

function renderPagination(pagination) {
    const nav = document.getElementById('paginationNav');
    const container = document.getElementById('pagination');

    if (!pagination || pagination.pages <= 1) {
        nav.style.display = 'none';
        return;
    }

    nav.style.display = 'block';

    const { page, pages } = pagination;
    let html = '';

    // Previous button
    html += `
        <li class="page-item ${page === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${page - 1}">Previous</a>
        </li>
    `;

    // Page numbers
    const maxPages = 5;
    let startPage = Math.max(1, page - Math.floor(maxPages / 2));
    let endPage = Math.min(pages, startPage + maxPages - 1);

    if (endPage - startPage < maxPages - 1) {
        startPage = Math.max(1, endPage - maxPages + 1);
    }

    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
        if (startPage > 2) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === page ? 'active' : ''}">
                <a class="page-link" href="#" data-page="${i}">${i}</a>
            </li>
        `;
    }

    if (endPage < pages) {
        if (endPage < pages - 1) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        html += `<li class="page-item"><a class="page-link" href="#" data-page="${pages}">${pages}</a></li>`;
    }

    // Next button
    html += `
        <li class="page-item ${page === pages ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${page + 1}">Next</a>
        </li>
    `;

    container.innerHTML = html;

    // Attach click handlers
    container.querySelectorAll('a.page-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetPage = parseInt(e.currentTarget.dataset.page);
            if (targetPage && targetPage !== page) {
                currentFilters.page = targetPage;
                loadFiles();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });
    });
}

function updateFilesCount(total) {
    const badge = document.getElementById('filesTotalBadge');
    badge.textContent = `${total} file${total !== 1 ? 's' : ''}`;
}

// ============================================================================
// FILE DETAILS MODAL
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

    let html = `
        <!-- File Info Section -->
        <div class="row mb-4">
            <div class="col-md-8">
                <h6 class="border-bottom pb-2">File Information</h6>
                <dl class="row">
                    <dt class="col-sm-4">Filename</dt>
                    <dd class="col-sm-8">${escapeHtml(file.filename)}</dd>

                    <dt class="col-sm-4">File Type</dt>
                    <dd class="col-sm-8"><span class="badge bg-primary">${file.file_type}</span></dd>

                    <dt class="col-sm-4">Size</dt>
                    <dd class="col-sm-8">${file.size_display}</dd>

                    ${file.media_metadata.duration_seconds ? `
                        <dt class="col-sm-4">Duration</dt>
                        <dd class="col-sm-8">${file.media_metadata.duration_seconds.toFixed(2)} seconds</dd>
                    ` : ''}

                    <dt class="col-sm-4">Uploaded</dt>
                    <dd class="col-sm-8">${file.uploaded_at}</dd>

                    ${file.local_path ? `
                        <dt class="col-sm-4">Local Path</dt>
                        <dd class="col-sm-8">
                            <code class="small">${escapeHtml(file.local_path)}</code>
                        </dd>
                    ` : ''}
                </dl>
            </div>

            <div class="col-md-4">
                <h6 class="border-bottom pb-2">Media Metadata</h6>
                <dl class="row">
                    ${file.media_metadata.resolution_width ? `
                        <dt class="col-sm-6">Resolution</dt>
                        <dd class="col-sm-6">${file.media_metadata.resolution_width}x${file.media_metadata.resolution_height}</dd>
                    ` : ''}

                    ${file.media_metadata.frame_rate ? `
                        <dt class="col-sm-6">Frame Rate</dt>
                        <dd class="col-sm-6">${file.media_metadata.frame_rate.toFixed(2)} fps</dd>
                    ` : ''}

                    ${file.media_metadata.codec_video ? `
                        <dt class="col-sm-6">Video Codec</dt>
                        <dd class="col-sm-6">${file.media_metadata.codec_video}</dd>
                    ` : ''}

                    ${file.media_metadata.codec_audio ? `
                        <dt class="col-sm-6">Audio Codec</dt>
                        <dd class="col-sm-6">${file.media_metadata.codec_audio}</dd>
                    ` : ''}

                    ${file.media_metadata.bitrate ? `
                        <dt class="col-sm-6">Bitrate</dt>
                        <dd class="col-sm-6">${(file.media_metadata.bitrate / 1000000).toFixed(1)} Mbps</dd>
                    ` : ''}
                </dl>
            </div>
        </div>
    `;

    // Proxy Section
    if (proxy) {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">Proxy Files</h6>
                <div class="alert alert-success">
                    <i class="bi bi-cloud-check"></i>
                    Proxy available: <code>${escapeHtml(proxy.filename)}</code> (${proxy.size_display})
                    <a href="${proxy.presigned_url}" target="_blank" class="btn btn-sm btn-primary float-end">
                        <i class="bi bi-play"></i> View on S3
                    </a>
                </div>
            </div>
        `;
    } else {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">Proxy Files</h6>
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle"></i> No proxy file available
                </div>
            </div>
        `;
    }

    // Analysis Jobs Section
    if (analysis_jobs && analysis_jobs.length > 0) {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">
                    Analysis Jobs <span class="badge bg-primary">${analysis_jobs.length}</span>
                </h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Type</th>
                                <th>Status</th>
                                <th>Started</th>
                                <th>Completed</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${analysis_jobs.map(job => `
                                <tr>
                                    <td>${job.analysis_type}</td>
                                    <td><span class="badge bg-${getStatusBadgeClass(job.status)}">${job.status}</span></td>
                                    <td>${job.started_at}</td>
                                    <td>${job.completed_at || 'N/A'}</td>
                                    <td>
                                        ${job.has_results ? `
                                            <a href="/history" class="btn btn-sm btn-primary">
                                                <i class="bi bi-graph-up"></i> View
                                            </a>
                                        ` : ''}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    } else {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">Analysis Jobs</h6>
                <p class="text-muted">No analysis jobs for this file</p>
            </div>
        `;
    }

    // Transcripts Section
    if (transcripts && transcripts.length > 0) {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">
                    Transcripts <span class="badge bg-info">${transcripts.length}</span>
                </h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Model</th>
                                <th>Language</th>
                                <th>Status</th>
                                <th>Words</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${transcripts.map(transcript => `
                                <tr>
                                    <td>${transcript.model_name}</td>
                                    <td>${transcript.language || 'N/A'}</td>
                                    <td><span class="badge bg-${getStatusBadgeClass(transcript.status)}">${transcript.status}</span></td>
                                    <td>${transcript.word_count ? transcript.word_count.toLocaleString() : 'N/A'}</td>
                                    <td>${transcript.created_at}</td>
                                    <td>
                                        <a href="/transcription" class="btn btn-sm btn-info">
                                            <i class="bi bi-eye"></i> View
                                        </a>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    } else {
        html += `
            <div class="mb-4">
                <h6 class="border-bottom pb-2">Transcripts</h6>
                <p class="text-muted">No transcripts for this file</p>
            </div>
        `;
    }

    container.innerHTML = html;
}

// ============================================================================
// FILE ACTIONS
// ============================================================================

async function createProxy(fileId) {
    if (!confirm('Create proxy for this file? This will transcode the video to 720p/15fps.')) {
        return;
    }

    try {
        showAlert('Creating proxy...', 'info');

        const response = await fetch(`/api/files/${fileId}/create-proxy`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to create proxy');
        }

        const result = await response.json();
        showAlert('Proxy created successfully', 'success');
        loadFiles();

    } catch (error) {
        console.error('Create proxy error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

async function startTranscription(fileId) {
    const model = prompt('Enter Whisper model (tiny, base, small, medium, large-v2, large-v3):', 'medium');
    if (!model) return;

    try {
        showAlert('Starting transcription...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-transcription`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_name: model })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to start transcription');
        }

        const result = await response.json();
        showAlert('Transcription started', 'success');
        loadFiles();

    } catch (error) {
        console.error('Start transcription error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

async function startRekognitionAnalysis(fileId) {
    // For simplicity, start label detection. In a full implementation, show a modal to select analysis types.
    if (!confirm('Start Rekognition label detection analysis?')) {
        return;
    }

    try {
        showAlert('Starting analysis...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-analysis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis_types: ['label_detection'],
                use_proxy: true
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to start analysis');
        }

        const result = await response.json();
        showAlert(`Started ${result.job_ids.length} analysis job(s)`, 'success');
        loadFiles();

    } catch (error) {
        console.error('Start analysis error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

async function startNovaAnalysis(fileId) {
    if (!confirm('Start Nova analysis with summary and chapters?')) {
        return;
    }

    try {
        showAlert('Starting Nova analysis...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-nova`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: 'us.amazon.nova-lite-v1:0',
                analysis_types: ['summary', 'chapters']
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to start Nova analysis');
        }

        const result = await response.json();
        showAlert('Nova analysis started', 'success');
        loadFiles();

    } catch (error) {
        console.error('Start Nova error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

async function downloadFile(fileId) {
    try {
        // Get file details to get S3 key
        const response = await fetch(`/api/files/${fileId}`);
        if (!response.ok) throw new Error('Failed to get file details');

        const data = await response.json();
        const file = data.file;

        // For proxy files, use presigned URL
        if (data.proxy && data.proxy.presigned_url) {
            window.open(data.proxy.presigned_url, '_blank');
        } else {
            showAlert('No downloadable file available (proxy not found)', 'warning');
        }

    } catch (error) {
        console.error('Download error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

async function deleteFile(fileId) {
    if (!confirm('Delete this file and all related data? This action cannot be undone.')) {
        return;
    }

    try {
        showAlert('Deleting file...', 'info');

        const response = await fetch(`/api/files/${fileId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to delete file');
        }

        const result = await response.json();
        showAlert('File deleted successfully', 'success');
        loadFiles();

    } catch (error) {
        console.error('Delete file error:', error);
        showAlert(`Error: ${error.message}`, 'danger');
    }
}

// ============================================================================
// S3 FILES
// ============================================================================

async function loadS3Files() {
    const container = document.getElementById('s3FilesContainer');
    container.innerHTML = '<div class="text-center"><div class="spinner-border"></div></div>';

    try {
        const response = await fetch('/api/s3-files');
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load S3 files');
        }

        const data = await response.json();
        renderS3Files(data.s3_files);
        s3FilesLoaded = true;

    } catch (error) {
        console.error('Failed to load S3 files:', error);
        container.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Failed to load S3 files: ${error.message}
            </div>
        `;
    }
}

function renderS3Files(files) {
    const container = document.getElementById('s3FilesContainer');

    if (files.length === 0) {
        container.innerHTML = '<p class="text-muted">No files stored in S3</p>';
        return;
    }

    const table = `
        <div class="table-responsive">
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th>Proxy File</th>
                        <th>S3 Key</th>
                        <th>Size</th>
                        <th>Source File</th>
                        <th>Uploaded</th>
                    </tr>
                </thead>
                <tbody>
                    ${files.map(file => `
                        <tr>
                            <td>${escapeHtml(file.proxy_filename)}</td>
                            <td><code class="small">${escapeHtml(file.s3_key)}</code></td>
                            <td>${file.size_display}</td>
                            <td>
                                ${file.source_id ? `
                                    <a href="#" class="link-primary view-source-btn" data-file-id="${file.source_id}">
                                        ${escapeHtml(file.source_filename)}
                                    </a>
                                ` : '<span class="text-muted">No source</span>'}
                            </td>
                            <td>${file.uploaded_at}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = table;

    // Attach click handlers for source file links
    container.querySelectorAll('.view-source-btn').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            viewFileDetails(fileId);
        });
    });
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function getStatusBadgeClass(status) {
    const statusMap = {
        'COMPLETED': 'success',
        'SUCCEEDED': 'success',
        'IN_PROGRESS': 'warning',
        'SUBMITTED': 'info',
        'FAILED': 'danger',
        'PENDING': 'secondary'
    };
    return statusMap[status] || 'secondary';
}
