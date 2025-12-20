import { showAlert } from './utils.js';

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

let currentFilters = {
    search: '',
    file_type: '',
    has_proxy: null,
    has_transcription: null,
    upload_from_date: '',
    upload_to_date: '',
    created_from_date: '',
    created_to_date: '',
    min_size: '',
    max_size: '',
    min_duration: '',
    max_duration: '',
    sort_by: 'uploaded_at',
    sort_order: 'desc',
    page: 1,
    per_page: 50
};

let currentFiles = [];
let currentPagination = null;
let s3FilesLoaded = false;
let importBrowsingPath = '';
let importBrowserParentPath = null;

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

    // Batch action buttons
    document.getElementById('batchProxyBtn').addEventListener('click', () => startBatchAction('proxy'));
    document.getElementById('batchTranscribeBtn').addEventListener('click', () => startBatchAction('transcribe'));
    document.getElementById('batchNovaBtn').addEventListener('click', () => startBatchAction('nova'));
    document.getElementById('batchRekognitionBtn').addEventListener('click', () => startBatchAction('rekognition'));

    // S3 files section (lazy load)
    const s3FilesCollapse = document.getElementById('s3FilesCollapse');
    s3FilesCollapse.addEventListener('show.bs.collapse', () => {
        if (!s3FilesLoaded) {
            loadS3Files();
        }
    });

    // Delete All S3 Files button
    const deleteAllS3Btn = document.getElementById('deleteAllS3Btn');
    if (deleteAllS3Btn) {
        deleteAllS3Btn.addEventListener('click', deleteAllS3Files);
    }

    // Import directory
    const importDirectoryBtn = document.getElementById('importDirectoryBtn');
    if (importDirectoryBtn) {
        importDirectoryBtn.addEventListener('click', importDirectory);
    }

    const importFolderModal = document.getElementById('importFolderBrowserModal');
    if (importFolderModal) {
        importFolderModal.addEventListener('show.bs.modal', () => {
            const existingPath = document.getElementById('importDirectoryPath').value.trim();
            importBrowseTo(existingPath || '');
        });
    }

    const importGoUpBtn = document.getElementById('importGoUpBtn');
    if (importGoUpBtn) {
        importGoUpBtn.addEventListener('click', () => {
            if (importBrowserParentPath) {
                importBrowseTo(importBrowserParentPath);
            }
        });
    }

    const importGoToPathBtn = document.getElementById('importGoToPathBtn');
    if (importGoToPathBtn) {
        importGoToPathBtn.addEventListener('click', () => {
            const pathInput = document.getElementById('importCurrentBrowsePath').value.trim();
            if (pathInput) {
                importBrowseTo(pathInput);
            }
        });
    }

    const importSelectFolderBtn = document.getElementById('importSelectFolderBtn');
    if (importSelectFolderBtn) {
        importSelectFolderBtn.addEventListener('click', () => {
            if (!importBrowsingPath) return;
            document.getElementById('importDirectoryPath').value = importBrowsingPath;
            const modal = bootstrap.Modal.getInstance(importFolderModal);
            if (modal) modal.hide();
        });
    }
}

function applyFilters() {
    currentFilters.file_type = document.getElementById('fileTypeFilter').value;

    const proxyFilter = document.getElementById('proxyFilter').value;
    currentFilters.has_proxy = proxyFilter === '' ? null : proxyFilter === 'true';

    const transcriptionFilter = document.getElementById('transcriptionFilter').value;
    currentFilters.has_transcription = transcriptionFilter === '' ? null : transcriptionFilter === 'true';

    // Upload date filters
    currentFilters.upload_from_date = document.getElementById('uploadFromDate').value;
    currentFilters.upload_to_date = document.getElementById('uploadToDate').value;

    // Created date filters
    currentFilters.created_from_date = document.getElementById('createdFromDate').value;
    currentFilters.created_to_date = document.getElementById('createdToDate').value;

    // Size filters (convert MB to bytes for backend)
    const minSize = document.getElementById('minSize').value;
    const maxSize = document.getElementById('maxSize').value;
    currentFilters.min_size = minSize ? parseInt(minSize) * 1024 * 1024 : '';
    currentFilters.max_size = maxSize ? parseInt(maxSize) * 1024 * 1024 : '';

    // Duration filters
    currentFilters.min_duration = document.getElementById('minDuration').value;
    currentFilters.max_duration = document.getElementById('maxDuration').value;

    currentFilters.page = 1;
    loadFiles();
}

function resetFilters() {
    // Reset filter values
    document.getElementById('searchInput').value = '';
    document.getElementById('fileTypeFilter').value = '';
    document.getElementById('proxyFilter').value = '';
    document.getElementById('transcriptionFilter').value = '';
    document.getElementById('uploadFromDate').value = '';
    document.getElementById('uploadToDate').value = '';
    document.getElementById('createdFromDate').value = '';
    document.getElementById('createdToDate').value = '';
    document.getElementById('minSize').value = '';
    document.getElementById('maxSize').value = '';
    document.getElementById('minDuration').value = '';
    document.getElementById('maxDuration').value = '';

    // Reset state
    currentFilters = {
        search: '',
        file_type: '',
        has_proxy: null,
        has_transcription: null,
        upload_from_date: '',
        upload_to_date: '',
        created_from_date: '',
        created_to_date: '',
        min_size: '',
        max_size: '',
        min_duration: '',
        max_duration: '',
        sort_by: 'uploaded_at',
        sort_order: 'desc',
        page: 1,
        per_page: 50
    };

    loadFiles();
}

// ============================================================================
// DIRECTORY IMPORT
// ============================================================================

async function importBrowseTo(path) {
    const folderList = document.getElementById('importFolderList');
    folderList.innerHTML = `
        <div class="text-center p-4">
            <div class="spinner-border" role="status"></div>
            <p class="mt-2 mb-0">Loading folders...</p>
        </div>
    `;

    try {
        const response = await fetch('/api/files/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to browse directory');
        }

        const data = await response.json();
        importBrowsingPath = data.current_path;
        importBrowserParentPath = data.parent_path;

        document.getElementById('importCurrentBrowsePath').value = data.current_path;
        document.getElementById('importGoUpBtn').disabled = !data.parent_path;

        if (data.drives && data.drives.length > 0) {
            document.getElementById('importDriveSelector').style.display = 'block';
            const driveButtons = document.getElementById('importDriveButtons');
            driveButtons.innerHTML = data.drives.map(drive =>
                `<button type="button" class="btn btn-sm btn-outline-primary import-drive-btn" data-path="${drive}">
                    <i class="bi bi-hdd"></i> ${drive}
                </button>`
            ).join('');

            driveButtons.querySelectorAll('.import-drive-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    importBrowseTo(btn.dataset.path);
                });
            });
        } else {
            document.getElementById('importDriveSelector').style.display = 'none';
        }

        if (!data.directories || data.directories.length === 0) {
            folderList.innerHTML = `
                <div class="text-center p-4 text-muted">
                    <i class="bi bi-folder-x fs-3"></i>
                    <p class="mt-2 mb-0">No subfolders found</p>
                </div>
            `;
            return;
        }

        folderList.innerHTML = data.directories.map(dir => `
            <button type="button" class="list-group-item list-group-item-action import-folder-item"
                    data-path="${dir.path}">
                <i class="bi bi-folder me-2"></i> ${dir.name}
            </button>
        `).join('');

        folderList.querySelectorAll('.import-folder-item').forEach(btn => {
            btn.addEventListener('click', () => {
                importBrowseTo(btn.dataset.path);
            });
        });

    } catch (error) {
        console.error('Browse error:', error);
        folderList.innerHTML = `
            <div class="alert alert-danger m-3">
                <i class="bi bi-exclamation-triangle"></i> ${error.message}
            </div>
        `;
    }
}

async function importDirectory() {
    const directoryPath = document.getElementById('importDirectoryPath').value.trim();
    const recursive = document.getElementById('importRecursive').checked;

    if (!directoryPath) {
        showAlert('Please enter a directory path to import', 'warning');
        return;
    }

    const importButton = document.getElementById('importDirectoryBtn');
    importButton.disabled = true;

    try {
        showAlert('Importing files...', 'info');

        const response = await fetch('/api/files/import-directory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                directory_path: directoryPath,
                recursive: recursive
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to import directory');
        }

        const result = await response.json();
        const message = `Imported ${result.imported} file(s) (scanned ${result.scanned}, ` +
            `skipped existing ${result.skipped_existing}, unsupported ${result.skipped_unsupported})`;
        showAlert(message, result.errors && result.errors.length > 0 ? 'warning' : 'success');

        if (result.errors && result.errors.length > 0) {
            console.warn('Import errors:', result.errors);
        }

        loadFiles();

    } catch (error) {
        console.error('Import error:', error);
        showAlert(`Import failed: ${error.message}`, 'danger');
    } finally {
        importButton.disabled = false;
    }
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
        updateSummary(data.summary);

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

    const getSortIcon = (field) => {
        if (currentFilters.sort_by !== field) {
            return '<i class="bi bi-arrow-down-up text-muted"></i>';
        }
        return currentFilters.sort_order === 'asc'
            ? '<i class="bi bi-arrow-up text-primary"></i>'
            : '<i class="bi bi-arrow-down text-primary"></i>';
    };

    const table = `
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th style="width: 30%; cursor: pointer;" class="sortable" data-sort="filename">
                            File ${getSortIcon('filename')}
                        </th>
                        <th style="width: 8%; cursor: pointer;" class="sortable" data-sort="file_type">
                            Type ${getSortIcon('file_type')}
                        </th>
                        <th style="width: 10%; cursor: pointer;" class="sortable" data-sort="size_bytes">
                            Size ${getSortIcon('size_bytes')}
                        </th>
                        <th style="width: 10%; cursor: pointer;" class="sortable" data-sort="duration_seconds">
                            Duration ${getSortIcon('duration_seconds')}
                        </th>
                        <th style="width: 12%">Resolution</th>
                        <th style="width: 15%">Status</th>
                        <th style="width: 10%; cursor: pointer;" class="sortable" data-sort="uploaded_at">
                            Uploaded ${getSortIcon('uploaded_at')}
                        </th>
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
    attachSortListeners();
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
        statusBadges.push('<span class="badge bg-success" title="Proxy available"><i class="bi bi-cloud-check"></i> Proxy</span>');
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

function attachSortListeners() {
    const sortableHeaders = document.querySelectorAll('.sortable');
    sortableHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const sortField = header.dataset.sort;

            // Toggle sort order if clicking same field, otherwise default to desc
            if (currentFilters.sort_by === sortField) {
                currentFilters.sort_order = currentFilters.sort_order === 'asc' ? 'desc' : 'asc';
            } else {
                currentFilters.sort_by = sortField;
                currentFilters.sort_order = 'desc';
            }

            currentFilters.page = 1;
            loadFiles();
        });
    });
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

    // Update batch files count
    const batchCount = document.getElementById('batchFilesCount');
    if (batchCount) {
        batchCount.textContent = `${total} file${total !== 1 ? 's' : ''}`;
    }
}

function updateSummary(summary) {
    const summaryContainer = document.getElementById('filesSummary');
    const countEl = document.getElementById('summaryCount');
    const sizeEl = document.getElementById('summarySize');
    const durationEl = document.getElementById('summaryDuration');

    if (summary && summary.total_count > 0) {
        countEl.textContent = summary.total_count.toLocaleString();
        sizeEl.textContent = summary.total_size_display || '0 B';
        durationEl.textContent = summary.total_duration_display || 'N/A';
        summaryContainer.style.display = 'block';
    } else {
        summaryContainer.style.display = 'none';
    }
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
    const countBadge = document.getElementById('s3FilesCountBadge');

    if (countBadge) {
        countBadge.textContent = `${files.length} file${files.length !== 1 ? 's' : ''}`;
    }

    if (files.length === 0) {
        container.innerHTML = '<p class="text-muted">No files stored in S3</p>';
        return;
    }

    const table = `
        <div class="table-responsive">
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>S3 Key</th>
                        <th>Size</th>
                        <th>Type</th>
                        <th>In Database</th>
                        <th>Last Modified</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${files.map(file => `
                        <tr>
                            <td>${escapeHtml(file.filename)}</td>
                            <td><code class="small">${escapeHtml(file.s3_key)}</code></td>
                            <td>${file.size_display}</td>
                            <td>
                                <span class="badge bg-${file.file_type === 'video' ? 'primary' : file.file_type === 'image' ? 'success' : 'secondary'}">
                                    ${file.file_type}
                                </span>
                            </td>
                            <td>
                                ${file.in_database ? `
                                    <span class="badge bg-success">
                                        <i class="bi bi-check-circle"></i> Yes
                                        ${file.file_id ? `<a href="#" class="text-white ms-1 view-file-btn" data-file-id="${file.file_id}"><i class="bi bi-eye"></i></a>` : ''}
                                    </span>
                                ` : '<span class="badge bg-warning text-dark"><i class="bi bi-exclamation-triangle"></i> No</span>'}
                            </td>
                            <td>${file.last_modified || 'N/A'}</td>
                            <td>
                                <div class="btn-group btn-group-sm" role="group">
                                    <button class="btn btn-outline-primary download-s3-btn" data-s3-key="${escapeHtml(file.s3_key)}" title="Download">
                                        <i class="bi bi-download"></i>
                                    </button>
                                    <button class="btn btn-outline-danger delete-s3-btn" data-s3-key="${escapeHtml(file.s3_key)}" data-filename="${escapeHtml(file.filename)}" title="Delete">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = table;

    // Attach click handlers
    container.querySelectorAll('.view-file-btn').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            viewFileDetails(fileId);
        });
    });

    container.querySelectorAll('.download-s3-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const s3Key = btn.dataset.s3Key;
            downloadS3File(s3Key);
        });
    });

    container.querySelectorAll('.delete-s3-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const s3Key = btn.dataset.s3Key;
            const filename = btn.dataset.filename;
            deleteS3File(s3Key, filename);
        });
    });
}

// ============================================================================
// S3 FILE OPERATIONS
// ============================================================================

async function downloadS3File(s3Key) {
    try {
        // Get presigned download URL
        const response = await fetch(`/api/s3-file/${encodeURIComponent(s3Key)}/download-url`);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to get download URL');
        }

        const data = await response.json();

        // Open download in new tab
        window.open(data.download_url, '_blank');

        showAlert('Download started! Check your downloads folder.', 'success');

    } catch (error) {
        console.error('Download S3 file error:', error);
        showAlert(`Failed to download file: ${error.message}`, 'danger');
    }
}

async function deleteS3File(s3Key, filename) {
    if (!confirm(`Are you sure you want to delete "${filename}" from S3?\n\nThis action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/s3-file/${encodeURIComponent(s3Key)}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to delete file');
        }

        showAlert(`File "${filename}" deleted successfully`, 'success');

        // Reload S3 files
        loadS3Files();

    } catch (error) {
        console.error('Delete S3 file error:', error);
        showAlert(`Failed to delete file: ${error.message}`, 'danger');
    }
}

async function deleteAllS3Files() {
    if (!confirm('⚠️ WARNING ⚠️\n\nAre you ABSOLUTELY SURE you want to delete ALL files from the S3 bucket?\n\nThis will permanently delete:\n- All uploaded videos\n- All proxy files\n- All Nova batch files\n- Everything in the bucket\n\nThis action CANNOT be undone!')) {
        return;
    }

    // Second confirmation
    const confirmText = prompt('Type "DELETE ALL" to confirm this destructive action:');
    if (confirmText !== 'DELETE ALL') {
        showAlert('Delete all cancelled', 'info');
        return;
    }

    try {
        const response = await fetch('/api/s3-files/delete-all', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ confirm: true })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to delete files');
        }

        const data = await response.json();
        showAlert(data.message, 'success');

        // Reload S3 files
        loadS3Files();

    } catch (error) {
        console.error('Delete all S3 files error:', error);
        showAlert(`Failed to delete files: ${error.message}`, 'danger');
    }
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

// ============================================================================
// BATCH PROCESSING
// ============================================================================

let currentBatchJob = null;
let batchProgressModal = null;
let batchStatusInterval = null;

async function startBatchAction(actionType) {
    // Get confirmation and options based on action type
    const options = await getBatchOptions(actionType);
    if (!options) {
        return; // User cancelled
    }

    try {
        // Extract file IDs from currently displayed/filtered files
        // This ensures batch operations only affect the files the user can currently see
        const fileIds = currentFiles.map(file => file.id).filter(id => id > 0);

        if (fileIds.length === 0) {
            showAlert('No files to process in the current view', 'warning');
            return;
        }

        // Build request body with file IDs and options
        const requestBody = {
            file_ids: fileIds,
            ...options
        };

        // Start batch job
        const response = await fetch(`/api/batch/${actionType}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to start batch job');
        }

        const data = await response.json();
        currentBatchJob = data.job_id;

        // Show progress modal
        showBatchProgressModal(actionType, data.total_files);

        // Start polling for progress
        startBatchProgressPolling();

    } catch (error) {
        console.error('Start batch error:', error);
        showAlert(`Failed to start batch ${actionType}: ${error.message}`, 'danger');
    }
}

async function getBatchOptions(actionType) {
    switch (actionType) {
        case 'proxy':
            return confirm('Create proxy videos (720p/15fps) for all filtered files?') ? {} : null;

        case 'transcribe':
            const model = prompt('Enter Whisper model (tiny, base, small, medium, large-v2, large-v3):', 'medium');
            if (!model) return null;

            const language = prompt('Enter language code (optional, e.g., "en" for English):', '');
            return {
                model_name: model,
                language: language || undefined
            };

        case 'nova':
            if (!confirm('Start Nova analysis (summary + chapters) for all filtered files with proxies?')) {
                return null;
            }
            return {
                model: 'us.amazon.nova-lite-v1:0',
                analysis_types: ['summary', 'chapters']
            };

        case 'rekognition':
            if (!confirm('Start Rekognition label detection for all filtered files?')) {
                return null;
            }
            return {
                analysis_types: ['label_detection'],
                use_proxy: true
            };

        default:
            return null;
    }
}

function showBatchProgressModal(actionType, totalFiles) {
    // Initialize modal if not already done
    if (!batchProgressModal) {
        batchProgressModal = new bootstrap.Modal(document.getElementById('batchProgressModal'));
    }

    // Set title
    const titles = {
        'proxy': 'Generating Proxy Videos',
        'transcribe': 'Transcribing Videos',
        'nova': 'Running Nova Analysis',
        'rekognition': 'Running Rekognition Analysis'
    };
    document.getElementById('batchActionTitle').textContent = titles[actionType] || 'Processing...';

    // Reset progress
    updateBatchProgress({
        status: 'RUNNING',
        progress_percent: 0,
        total_files: totalFiles,
        completed_files: 0,
        failed_files: 0,
        current_file: null,
        elapsed_seconds: 0,
        errors: []
    });

    // Show modal
    batchProgressModal.show();

    // Setup cancel button
    const cancelBtn = document.getElementById('batchCancelBtn');
    cancelBtn.onclick = cancelBatchJob;
    cancelBtn.style.display = 'inline-block';

    // Hide done button
    document.getElementById('batchDoneBtn').style.display = 'none';

    // Disable close button
    document.getElementById('batchCloseBtn').disabled = true;
}

function updateBatchProgress(data) {
    // Progress bar
    const progressBar = document.getElementById('batchProgressBar');
    const progressText = document.getElementById('batchProgressText');
    progressBar.style.width = `${data.progress_percent}%`;
    progressText.textContent = `${data.progress_percent.toFixed(1)}%`;

    // Update bar color based on status
    progressBar.className = 'progress-bar';
    if (data.status === 'COMPLETED') {
        progressBar.classList.add('bg-success');
    } else if (data.status === 'FAILED' || data.status === 'CANCELLED') {
        progressBar.classList.add('bg-danger');
        progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');
    } else {
        progressBar.classList.add('progress-bar-striped', 'progress-bar-animated');
    }

    // Status text
    document.getElementById('batchStatusText').textContent = data.status;

    // Count text
    document.getElementById('batchCountText').textContent =
        `${data.completed_files + data.failed_files} / ${data.total_files}`;

    // Current file
    const currentFileDiv = document.getElementById('batchCurrentFile');
    const currentFileName = document.getElementById('batchCurrentFileName');
    if (data.current_file) {
        currentFileName.textContent = data.current_file;
        currentFileDiv.style.display = 'block';
    } else {
        currentFileDiv.style.display = 'none';
    }

    // Statistics
    if (data.status === 'RUNNING' || data.status === 'COMPLETED') {
        document.getElementById('batchStats').style.display = 'flex';
        document.getElementById('batchCompleted').textContent = data.completed_files;
        document.getElementById('batchFailed').textContent = data.failed_files;
        document.getElementById('batchElapsed').textContent = `${data.elapsed_seconds.toFixed(1)}s`;
    }

    // Errors
    if (data.errors && data.errors.length > 0) {
        document.getElementById('batchErrorsSection').style.display = 'block';
        document.getElementById('batchErrorCount').textContent = data.errors.length;

        const errorsContainer = document.getElementById('batchErrorsContainer');
        errorsContainer.innerHTML = data.errors.map(error => `
            <div class="list-group-item list-group-item-danger">
                <strong>${escapeHtml(error.filename || 'Unknown file')}</strong><br>
                <small>${escapeHtml(error.error)}</small>
            </div>
        `).join('');
    }

    // Handle completion
    if (data.status === 'COMPLETED' || data.status === 'CANCELLED' || data.status === 'FAILED') {
        stopBatchProgressPolling();

        // Hide cancel, show done
        document.getElementById('batchCancelBtn').style.display = 'none';
        document.getElementById('batchDoneBtn').style.display = 'inline-block';

        // Enable close button
        document.getElementById('batchCloseBtn').disabled = false;

        // Reload files
        loadFiles();

        // Show completion alert
        if (data.status === 'COMPLETED') {
            const msg = `Batch processing completed: ${data.completed_files} succeeded, ${data.failed_files} failed`;
            showAlert(msg, data.failed_files > 0 ? 'warning' : 'success');
        }
    }
}

function startBatchProgressPolling() {
    // Poll every 2 seconds
    batchStatusInterval = setInterval(async () => {
        if (!currentBatchJob) {
            stopBatchProgressPolling();
            return;
        }

        try {
            const response = await fetch(`/api/batch/${currentBatchJob}/status`);
            if (!response.ok) {
                throw new Error('Failed to get batch status');
            }

            const data = await response.json();
            updateBatchProgress(data);

        } catch (error) {
            console.error('Batch status polling error:', error);
        }
    }, 2000);
}

function stopBatchProgressPolling() {
    if (batchStatusInterval) {
        clearInterval(batchStatusInterval);
        batchStatusInterval = null;
    }
}

async function cancelBatchJob() {
    if (!currentBatchJob) return;

    if (!confirm('Cancel this batch job?')) {
        return;
    }

    try {
        const response = await fetch(`/api/batch/${currentBatchJob}/cancel`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to cancel batch job');
        }

        showAlert('Batch job cancelled', 'info');

    } catch (error) {
        console.error('Cancel batch error:', error);
        showAlert(`Failed to cancel batch job: ${error.message}`, 'danger');
    }
}
