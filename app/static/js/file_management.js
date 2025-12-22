import { showAlert } from './utils.js';

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

let currentFilters = {
    search: '',
    file_type: '',
    has_proxy: null,
    has_transcription: null,
    has_nova_analysis: null,
    has_rekognition_analysis: null,
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

const FILE_MANAGEMENT_STATE_KEY = 'fileManagementState';
const BATCH_FETCH_PAGE_SIZE = 500;
let pendingScrollY = null;
let currentFiles = [];
let currentPagination = null;
let currentTranscriptId = null;
let s3FilesLoaded = false;
let importBrowsingPath = '';
let importBrowserParentPath = null;
let currentBatchActionType = null;  // Track current batch action type

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    if (!restoreFileManagementState()) {
        loadFiles();
    }

    // Check URL parameters for auto-opening modals
    setTimeout(() => handleURLParameters(), 500);  // Delay to ensure files are loaded
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

    initializeBatchOptionsModal();
    initializeSingleOptionsModal();

    const transcriptModal = document.getElementById('transcriptDetailsModal');
    if (transcriptModal) {
        transcriptModal.addEventListener('hidden.bs.modal', () => {
            currentTranscriptId = null;
        });
    }

    document.querySelectorAll('.download-transcript-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            if (!currentTranscriptId) return;

            const format = btn.dataset.format;
            const link = document.createElement('a');
            link.href = `/transcriptions/api/transcript/${currentTranscriptId}/download?format=${format}`;
            link.download = `transcript_${currentTranscriptId}.${format}`;
            link.click();
        });
    });
}

function applyFilters() {
    currentFilters.file_type = document.getElementById('fileTypeFilter').value;

    const proxyFilter = document.getElementById('proxyFilter').value;
    currentFilters.has_proxy = proxyFilter === '' ? null : proxyFilter === 'true';

    const transcriptionFilter = document.getElementById('transcriptionFilter').value;
    currentFilters.has_transcription = transcriptionFilter === '' ? null : transcriptionFilter === 'true';

    const novaFilter = document.getElementById('novaFilter').value;
    currentFilters.has_nova_analysis = novaFilter === '' ? null : novaFilter === 'true';

    const rekognitionFilter = document.getElementById('rekognitionFilter').value;
    currentFilters.has_rekognition_analysis = rekognitionFilter === '' ? null : rekognitionFilter === 'true';

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
    document.getElementById('novaFilter').value = '';
    document.getElementById('rekognitionFilter').value = '';
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
        has_nova_analysis: null,
        has_rekognition_analysis: null,
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

function saveFileManagementState() {
    const state = {
        filters: currentFilters,
        scrollY: window.scrollY
    };
    sessionStorage.setItem(FILE_MANAGEMENT_STATE_KEY, JSON.stringify(state));
}

function restoreFileManagementState() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('restore') !== '1') {
        return false;
    }

    const rawState = sessionStorage.getItem(FILE_MANAGEMENT_STATE_KEY);
    if (!rawState) {
        return false;
    }

    try {
        const state = JSON.parse(rawState);
        if (!state || !state.filters) {
            return false;
        }

        currentFilters = { ...currentFilters, ...state.filters };
        applyFiltersToInputs();
        if (typeof state.scrollY === 'number') {
            pendingScrollY = state.scrollY;
        }
        loadFiles();
        return true;
    } catch (error) {
        console.warn('Failed to restore file management state:', error);
        return false;
    }
}

function applyFiltersToInputs() {
    document.getElementById('searchInput').value = currentFilters.search || '';
    document.getElementById('fileTypeFilter').value = currentFilters.file_type || '';
    document.getElementById('proxyFilter').value = normalizeTriState(currentFilters.has_proxy);
    document.getElementById('transcriptionFilter').value = normalizeTriState(currentFilters.has_transcription);
    document.getElementById('novaFilter').value = normalizeTriState(currentFilters.has_nova_analysis);
    document.getElementById('rekognitionFilter').value = normalizeTriState(currentFilters.has_rekognition_analysis);
    document.getElementById('uploadFromDate').value = currentFilters.upload_from_date || '';
    document.getElementById('uploadToDate').value = currentFilters.upload_to_date || '';
    document.getElementById('createdFromDate').value = currentFilters.created_from_date || '';
    document.getElementById('createdToDate').value = currentFilters.created_to_date || '';
    document.getElementById('minSize').value = toMegabytes(currentFilters.min_size);
    document.getElementById('maxSize').value = toMegabytes(currentFilters.max_size);
    document.getElementById('minDuration').value = currentFilters.min_duration || '';
    document.getElementById('maxDuration').value = currentFilters.max_duration || '';

    const hasAdvancedFilters = currentFilters.min_size || currentFilters.max_size ||
        currentFilters.min_duration || currentFilters.max_duration;
    const advancedFiltersCollapse = document.getElementById('advancedFiltersCollapse');
    if (hasAdvancedFilters && advancedFiltersCollapse) {
        const collapse = new bootstrap.Collapse(advancedFiltersCollapse, { toggle: false });
        collapse.show();
    }
}

function normalizeTriState(value) {
    if (value === null || value === undefined || value === '') {
        return '';
    }
    return value ? 'true' : 'false';
}

function toMegabytes(value) {
    if (value === null || value === undefined || value === '') {
        return '';
    }
    return Math.round(parseInt(value, 10) / (1024 * 1024));
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
        const params = buildFileQueryParams();
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
        if (pendingScrollY !== null) {
            window.scrollTo(0, pendingScrollY);
            pendingScrollY = null;
        }

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
                        <th style="width: 9%; cursor: pointer;" class="sortable" data-sort="size_bytes">
                            Size ${getSortIcon('size_bytes')}
                        </th>
                        <th style="width: 7%">Proxy Size</th>
                        <th style="width: 8%; cursor: pointer;" class="sortable" data-sort="duration_seconds">
                            Duration ${getSortIcon('duration_seconds')}
                        </th>
                        <th style="width: 9%">Resolution</th>
                        <th style="width: 13%">Status</th>
                        <th style="width: 9%">Created</th>
                        <th style="width: 9%; cursor: pointer;" class="sortable" data-sort="uploaded_at">
                            Uploaded ${getSortIcon('uploaded_at')}
                        </th>
                        <th style="width: 11%">Actions</th>
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
        const shortTranscript = file.max_completed_transcript_chars !== null &&
            file.max_completed_transcript_chars !== undefined &&
            file.max_completed_transcript_chars < 20;
        const transcriptBadgeClass = shortTranscript ? 'bg-warning' : 'bg-info';
        const transcriptTitle = shortTranscript
            ? `${file.completed_transcripts} completed transcripts (short transcript)`
            : `${file.completed_transcripts} completed transcripts`;
        statusBadges.push(
            `<a href="#" class="badge ${transcriptBadgeClass} text-decoration-none action-view-transcript" data-file-id="${file.id}" title="${transcriptTitle}">
                <i class="bi bi-mic"></i> ${file.completed_transcripts}
            </a>`
        );
    }
    if (file.total_analyses > 0) {
        const badgeClass = file.running_analyses > 0 ? 'bg-warning' : 'bg-primary';
        const icon = file.running_analyses > 0 ? 'hourglass-split' : 'graph-up';
        statusBadges.push(
            `<a href="#" class="badge ${badgeClass} text-decoration-none action-view-analysis" data-file-id="${file.id}" title="${file.completed_analyses}/${file.total_analyses} analyses">
                <i class="bi bi-${icon}"></i> ${file.completed_analyses}/${file.total_analyses}
            </a>`
        );
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
            <td>${file.proxy_size_display ? `<span class="text-success">${file.proxy_size_display}</span>` : '<span class="text-muted">—</span>'}</td>
            <td>${file.duration_display || 'N/A'}</td>
            <td>${file.resolution || 'N/A'}</td>
            <td>
                <div class="d-flex flex-wrap gap-1">
                    ${statusBadges.join('')}
                    ${statusBadges.length === 0 ? '<span class="text-muted small">No processing</span>' : ''}
                </div>
            </td>
            <td>${file.created_at || 'N/A'}</td>
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

    document.querySelectorAll('.action-view-transcript').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            openLatestTranscript(fileId);
        });
    });

    document.querySelectorAll('.action-view-analysis').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            openLatestNovaAnalysis(fileId);
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

    updateNovaBatchModeAvailability(total);
}

function updateSummary(summary) {
    const summaryContainer = document.getElementById('filesSummary');
    const countEl = document.getElementById('summaryCount');
    const sizeEl = document.getElementById('summarySize');
    const proxySizeEl = document.getElementById('summaryProxySize');
    const durationEl = document.getElementById('summaryDuration');

    if (summary && summary.total_count > 0) {
        countEl.textContent = summary.total_count.toLocaleString();
        sizeEl.textContent = summary.total_size_display || '0 B';
        proxySizeEl.textContent = summary.total_proxy_size_display || '0 B';
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
        <div class="mb-4">
            <h6 class="border-bottom pb-2">Actions</h6>
            <div class="d-flex flex-wrap gap-2">
                ${file.file_type === 'video' ? `
                    <button class="btn btn-sm btn-outline-primary detail-transcribe-btn" data-file-id="${file.id}">
                        <i class="bi bi-mic"></i> Transcribe
                    </button>
                ` : ''}
                <button class="btn btn-sm btn-outline-success detail-rekognition-btn" data-file-id="${file.id}">
                    <i class="bi bi-eye"></i> Rekognition
                </button>
                ${file.file_type === 'video' ? `
                    <button class="btn btn-sm btn-outline-warning detail-nova-btn" data-file-id="${file.id}">
                        <i class="bi bi-stars"></i> Nova
                    </button>
                ` : ''}
            </div>
        </div>
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
                                        <a href="/dashboard/${job.job_id || job.id}" class="btn btn-sm btn-primary detail-view-analysis">
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
                                        <button type="button" class="btn btn-sm btn-info detail-view-transcript" data-transcript-id="${transcript.id}">
                                            <i class="bi bi-eye"></i> View
                                        </button>
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
    attachFileDetailsActionListeners(container);
}

function attachFileDetailsActionListeners(container) {
    container.querySelectorAll('.detail-transcribe-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startTranscription(fileId);
        });
    });

    container.querySelectorAll('.detail-rekognition-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startRekognitionAnalysis(fileId);
        });
    });

    container.querySelectorAll('.detail-nova-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const fileId = parseInt(e.currentTarget.dataset.fileId);
            startNovaAnalysis(fileId);
        });
    });

    container.querySelectorAll('.detail-view-analysis').forEach(link => {
        link.addEventListener('click', () => {
            saveFileManagementState();
        });
    });

    container.querySelectorAll('.detail-view-transcript').forEach(link => {
        link.addEventListener('click', (e) => {
            const transcriptId = parseInt(e.currentTarget.dataset.transcriptId, 10);
            if (transcriptId) {
                openTranscriptDetails(transcriptId);
            }
        });
    });
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

async function openLatestTranscript(fileId) {
    try {
        const response = await fetch(`/api/files/${fileId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load file details');
        }

        const data = await response.json();
        const transcripts = data.transcripts || [];
        const completed = transcripts.filter(t => t.status === 'COMPLETED');
        if (completed.length === 0) {
            showAlert('No completed transcripts found for this file.', 'warning');
            return;
        }

        completed.sort((a, b) => {
            const aDate = new Date(a.completed_at || a.created_at || 0).getTime();
            const bDate = new Date(b.completed_at || b.created_at || 0).getTime();
            return bDate - aDate;
        });

        const transcriptId = completed[0].id;
        openTranscriptDetails(transcriptId);
    } catch (error) {
        console.error('Open transcript error:', error);
        showAlert(`Failed to open transcript: ${error.message}`, 'danger');
    }
}

async function openTranscriptDetails(transcriptId) {
    const modalEl = document.getElementById('transcriptDetailsModal');
    const modalBody = document.getElementById('transcriptDetailsBody');
    if (!modalEl || !modalBody) {
        showAlert('Transcript details modal not available.', 'warning');
        return;
    }

    currentTranscriptId = transcriptId;
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
                        <strong>Model:</strong> <span class="badge bg-primary">${escapeHtml(transcript.model_name || 'N/A')}</span>
                    </div>
                    <div class="col-md-3">
                        <strong>Language:</strong> ${transcript.language ? transcript.language.toUpperCase() : 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <strong>Duration:</strong> ${formatDurationUI(transcript.duration_seconds)}
                    </div>
                    <div class="col-md-3">
                        <strong>File Size:</strong> ${formatFileSize(transcript.file_size)}
                    </div>
                    <div class="col-md-3">
                        <strong>Words:</strong> ${formatCount(transcript.word_count)}
                    </div>
                    <div class="col-md-3">
                        <strong>Characters:</strong> ${formatCount(transcript.character_count)}
                    </div>
                    <div class="col-md-3">
                        <strong>Confidence:</strong> ${transcript.confidence_score ? transcript.confidence_score.toFixed(2) : 'N/A'}
                    </div>
                    <div class="col-md-3">
                        <strong>Created:</strong> ${formatTranscriptDate(transcript.created_at)}
                    </div>
                    <div class="col-md-3">
                        <strong>Completed:</strong> ${formatTranscriptDate(transcript.completed_at)}
                    </div>
                    <div class="col-md-3">
                        <strong>Processing Time:</strong> ${transcript.processing_time ? transcript.processing_time.toFixed(1) + 's' : 'N/A'}
                    </div>
                </div>
            </div>
            ${transcript.error_message ? `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i> ${escapeHtml(transcript.error_message)}
                </div>
            ` : ''}
            <div class="card">
                <div class="card-header">
                    <h6 class="mb-0">Transcript Text</h6>
                </div>
                <div class="card-body" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">
                    ${transcriptText || '<span class="text-muted">No transcript text available.</span>'}
                </div>
            </div>
        `;
    } catch (error) {
        console.error('Transcript details error:', error);
        modalBody.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Failed to load transcript: ${escapeHtml(error.message)}
            </div>
        `;
    }
}

async function openLatestNovaAnalysis(fileId) {
    try {
        const response = await fetch(`/api/files/${fileId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to load file details');
        }

        const data = await response.json();
        const analysisJobs = data.analysis_jobs || [];
        const novaJobs = analysisJobs.filter(job =>
            job.analysis_type === 'nova' && (job.status === 'SUCCEEDED' || job.status === 'COMPLETED')
        );

        if (novaJobs.length === 0) {
            showAlert('No completed Nova analyses found for this file.', 'warning');
            return;
        }

        novaJobs.sort((a, b) => {
            const aDate = new Date(a.completed_at || a.started_at || 0).getTime();
            const bDate = new Date(b.completed_at || b.started_at || 0).getTime();
            return bDate - aDate;
        });

        const job = novaJobs[0];
        const jobId = job.job_id || job.id;
        if (!jobId) {
            showAlert('Nova analysis job id missing.', 'warning');
            return;
        }

        saveFileManagementState();
        window.location.href = `/dashboard/${jobId}`;
    } catch (error) {
        console.error('Open Nova analysis error:', error);
        showAlert(`Failed to open Nova analysis: ${error.message}`, 'danger');
    }
}

async function startTranscription(fileId) {
    const options = await getSingleOptions('transcribe', fileId);
    if (!options) return;

    try {
        showAlert('Starting transcription...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-transcription`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
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
    const options = await getSingleOptions('rekognition', fileId);
    if (!options) return;

    try {
        showAlert('Starting analysis...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-analysis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
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
    const options = await getSingleOptions('nova', fileId);
    if (!options) return;

    try {
        showAlert('Starting Nova analysis...', 'info');

        const response = await fetch(`/api/files/${fileId}/start-nova`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
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

function formatFileSize(bytes) {
    if (bytes === 0 || !bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function formatCount(count) {
    if (count === null || count === undefined || count === 0) {
        return 'N/A';
    }
    return count.toLocaleString();
}

function formatDurationUI(seconds) {
    if (seconds === null || seconds === undefined || seconds === 0) {
        return 'N/A';
    }

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
        return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
        return `${minutes}m ${secs}s`;
    }
    return `${secs}s`;
}

// Alias for compatibility (used in batch progress)
function formatDuration(seconds) {
    return formatDurationUI(seconds);
}

function formatTranscriptDate(isoDate) {
    if (!isoDate) return 'N/A';
    const date = new Date(isoDate);
    if (isNaN(date.getTime())) return 'N/A';
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
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
let batchOptionsModal = null;
let batchOptionsResolve = null;
let batchOptionsResolved = false;
let batchOptionsAction = null;
let singleOptionsModal = null;
let singleOptionsResolve = null;
let singleOptionsResolved = false;
let singleOptionsAction = null;
let singleOptionsFileId = null;
let novaModelsLoaded = false;
const NOVA_BATCH_MIN_FILES = 100;

function updateNovaProcessingSelect(selectId, noteId, fileCount, isSingle) {
    const select = document.getElementById(selectId);
    if (!select) return;

    const batchOption = select.querySelector('option[value="batch"]');
    if (!batchOption) return;

    const meetsMinimum = fileCount >= NOVA_BATCH_MIN_FILES;
    batchOption.disabled = !meetsMinimum;

    if (!meetsMinimum && select.value === 'batch') {
        select.value = 'realtime';
    }

    const note = document.getElementById(noteId);
    if (!note) return;

    if (meetsMinimum) {
        note.textContent = 'Batch runs via Bedrock batch jobs.';
    } else if (isSingle) {
        note.textContent = `Batch requires at least ${NOVA_BATCH_MIN_FILES} files and is only available for batch runs.`;
    } else {
        note.textContent = `Batch requires at least ${NOVA_BATCH_MIN_FILES} files in the current view (currently ${fileCount}).`;
    }
}

function updateNovaBatchModeAvailability(totalFiles) {
    const safeTotal = Number.isFinite(totalFiles) ? totalFiles : 0;
    updateNovaProcessingSelect('batchNovaProcessingMode', 'batchNovaProcessingNote', safeTotal, false);
    updateNovaProcessingSelect('singleNovaProcessingMode', 'singleNovaProcessingNote', 1, true);
}

function getCurrentFileTotal() {
    if (currentPagination && Number.isFinite(currentPagination.total)) {
        return currentPagination.total;
    }
    if (Array.isArray(currentFiles)) {
        return currentFiles.length;
    }
    return 0;
}

function buildFileQueryParams(overrides = {}) {
    const params = new URLSearchParams();
    const merged = { ...currentFilters, ...overrides };
    Object.keys(merged).forEach(key => {
        const value = merged[key];
        if (value !== '' && value !== null && value !== undefined) {
            params.append(key, value);
        }
    });
    return params;
}

async function fetchFilteredFileIds() {
    const total = getCurrentFileTotal();
    if (!total) {
        return [];
    }

    const perPage = Math.min(BATCH_FETCH_PAGE_SIZE, total);
    const totalPages = Math.ceil(total / perPage);
    const fileIds = [];

    for (let page = 1; page <= totalPages; page += 1) {
        const params = buildFileQueryParams({ page, per_page: perPage });
        const response = await fetch(`/api/files?${params.toString()}`);
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Failed to fetch batch files');
        }

        const data = await response.json();
        (data.files || []).forEach(file => {
            if (file && file.id > 0) {
                fileIds.push(file.id);
            }
        });
    }

    return fileIds;
}

async function startBatchAction(actionType) {
    // Get confirmation and options based on action type
    const options = await getBatchOptions(actionType);
    if (!options) {
        return; // User cancelled
    }

    try {
        // Extract file IDs from the full filtered result set
        const fileIds = await fetchFilteredFileIds();

        if (fileIds.length === 0) {
            showAlert('No files to process for the current filters', 'warning');
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
        currentBatchActionType = actionType;  // Store action type

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
    return new Promise((resolve) => {
        const modalEl = document.getElementById('batchOptionsModal');
        if (!modalEl) {
            resolve(null);
            return;
        }

        if (!batchOptionsModal) {
            batchOptionsModal = new bootstrap.Modal(modalEl);
            modalEl.addEventListener('hidden.bs.modal', () => {
                if (!batchOptionsResolved) {
                    resolveBatchOptions(null);
                }
            });
        }

        batchOptionsAction = actionType;
        batchOptionsResolve = resolve;
        batchOptionsResolved = false;

        const form = document.getElementById('batchOptionsForm');
        if (form) {
            form.reset();
        }

        const description = document.getElementById('batchOptionsDescription');
        const descriptions = {
            proxy: 'Generate 720p/15fps proxies for all eligible videos in the current view.',
            transcribe: 'Configure Whisper transcription settings for the current file set.',
            nova: 'Choose Nova model and analysis types for proxy-backed videos.',
            rekognition: 'Select Rekognition analysis types and target files.'
        };
        if (description) {
            description.textContent = descriptions[actionType] || 'Configure batch settings.';
        }

        const errorEl = document.getElementById('batchOptionsError');
        if (errorEl) {
            errorEl.classList.add('d-none');
            errorEl.textContent = '';
        }

        document.querySelectorAll('.batch-options-group').forEach(group => {
            group.style.display = group.dataset.action === actionType ? 'block' : 'none';
        });

        const confirmBtn = document.getElementById('batchOptionsConfirmBtn');
        if (confirmBtn) {
            const labels = {
                proxy: 'Start Proxy Batch',
                transcribe: 'Start Transcription Batch',
                nova: 'Start Nova Batch',
                rekognition: 'Start Rekognition Batch'
            };
            confirmBtn.textContent = labels[actionType] || 'Start Batch';
        }

        if (actionType === 'transcribe') {
            updateTranscribeProviderUI('batch');
        }

        if (actionType === 'nova') {
            loadNovaModels();
            updateNovaBatchModeAvailability(getCurrentFileTotal());
        }

        batchOptionsModal.show();
    });
}

function initializeBatchOptionsModal() {
    const modalEl = document.getElementById('batchOptionsModal');
    if (!modalEl) return;

    const confirmBtn = document.getElementById('batchOptionsConfirmBtn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            const options = buildBatchOptions(batchOptionsAction);
            if (!options) {
                return;
            }
            resolveBatchOptions(options);
            if (batchOptionsModal) {
                batchOptionsModal.hide();
            }
        });
    }

    const cancelBtn = document.getElementById('batchOptionsCancelBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            resolveBatchOptions(null);
        });
    }

    const providerSelect = document.getElementById('batchTranscribeProvider');
    if (providerSelect) {
        providerSelect.addEventListener('change', () => updateTranscribeProviderUI('batch'));
    }
}

function resolveBatchOptions(value) {
    if (batchOptionsResolved) return;
    batchOptionsResolved = true;
    if (batchOptionsResolve) {
        batchOptionsResolve(value);
    }
    batchOptionsResolve = null;
}

function updateTranscribeProviderUI(prefix) {
    const providerSelect = document.getElementById(`${prefix}TranscribeProvider`);
    if (!providerSelect) return;
    const isNova = providerSelect.value === 'nova_sonic';
    document.querySelectorAll(`.${prefix}-whisper-settings`).forEach(group => {
        group.style.display = isNova ? 'none' : '';
    });
}

function buildBatchOptions(actionType) {
    const errorEl = document.getElementById('batchOptionsError');
    if (errorEl) {
        errorEl.classList.add('d-none');
        errorEl.textContent = '';
    }

    switch (actionType) {
        case 'proxy':
            return {};
        case 'transcribe': {
            const provider = document.getElementById('batchTranscribeProvider')?.value || 'whisper';
            const model = document.getElementById('batchTranscribeModel')?.value || 'medium';
            const language = document.getElementById('batchTranscribeLanguage')?.value.trim();
            const force = !!document.getElementById('batchTranscribeForce')?.checked;
            const device = document.getElementById('batchTranscribeDevice')?.value || 'auto';
            const computeType = document.getElementById('batchTranscribeCompute')?.value || 'default';
            return {
                provider: provider,
                model_size: model,
                language: language || undefined,
                force: force,
                device: device,
                compute_type: computeType
            };
        }
        case 'nova': {
            const model = document.getElementById('batchNovaModel')?.value || 'lite';
            const analysisTypes = Array.from(document.querySelectorAll('.batch-nova-type:checked'))
                .map(input => input.value);
            if (analysisTypes.length === 0) {
                showBatchOptionsError('Select at least one Nova analysis type.');
                return null;
            }
            const processingMode = document.getElementById('batchNovaProcessingMode')?.value || 'realtime';
            const options = {
                summary_depth: document.getElementById('batchNovaSummaryDepth')?.value || 'standard',
                language: document.getElementById('batchNovaLanguage')?.value || 'auto'
            };
            return {
                model: model,
                analysis_types: analysisTypes,
                options: options,
                processing_mode: processingMode
            };
        }
        case 'rekognition': {
            const analysisTypes = Array.from(document.querySelectorAll('.batch-rekognition-type:checked'))
                .map(input => input.value);
            if (analysisTypes.length === 0) {
                showBatchOptionsError('Select at least one Rekognition analysis type.');
                return null;
            }
            const useProxy = !!document.getElementById('batchRekognitionUseProxy')?.checked;
            return {
                analysis_types: analysisTypes,
                use_proxy: useProxy
            };
        }
        default:
            return null;
    }
}

async function getSingleOptions(actionType, fileId) {
    return new Promise((resolve) => {
        const modalEl = document.getElementById('singleOptionsModal');
        if (!modalEl) {
            resolve(null);
            return;
        }

        if (!singleOptionsModal) {
            singleOptionsModal = new bootstrap.Modal(modalEl);
            modalEl.addEventListener('hidden.bs.modal', () => {
                if (!singleOptionsResolved) {
                    resolveSingleOptions(null);
                }
            });
        }

        singleOptionsAction = actionType;
        singleOptionsFileId = fileId;
        singleOptionsResolve = resolve;
        singleOptionsResolved = false;

        const form = document.getElementById('singleOptionsForm');
        if (form) form.reset();

        const description = document.getElementById('singleOptionsDescription');
        if (description) {
            const descriptions = {
                transcribe: 'Choose transcription settings for this file.',
                nova: 'Choose Nova analysis settings for this file.',
                rekognition: 'Choose Rekognition settings for this file.'
            };
            description.textContent = descriptions[actionType] || 'Configure processing settings.';
        }

        const errorEl = document.getElementById('singleOptionsError');
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.classList.add('d-none');
        }

        document.querySelectorAll('.single-options-group').forEach(group => {
            group.style.display = group.dataset.action === actionType ? '' : 'none';
        });

        const confirmBtn = document.getElementById('singleOptionsConfirmBtn');
        if (confirmBtn) {
            const labels = {
                transcribe: 'Start Transcription',
                nova: 'Start Nova Analysis',
                rekognition: 'Start Rekognition Analysis'
            };
            confirmBtn.textContent = labels[actionType] || 'Start';
        }

        setSingleDefaults(actionType);
        loadNovaModels();
        if (actionType === 'nova') {
            updateNovaBatchModeAvailability(getCurrentFileTotal());
        }

        singleOptionsModal.show();
    });
}

function initializeSingleOptionsModal() {
    const modalEl = document.getElementById('singleOptionsModal');
    if (!modalEl) return;

    const confirmBtn = document.getElementById('singleOptionsConfirmBtn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            const options = buildSingleOptions(singleOptionsAction);
            if (!options) return;
            resolveSingleOptions(options);
            if (singleOptionsModal) {
                singleOptionsModal.hide();
            }
        });
    }

    const cancelBtn = document.getElementById('singleOptionsCancelBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            resolveSingleOptions(null);
        });
    }

    const providerSelect = document.getElementById('singleTranscribeProvider');
    if (providerSelect) {
        providerSelect.addEventListener('change', () => updateTranscribeProviderUI('single'));
    }
}

function resolveSingleOptions(value) {
    if (singleOptionsResolved) return;
    singleOptionsResolved = true;
    if (singleOptionsResolve) {
        singleOptionsResolve(value);
    }
    singleOptionsResolve = null;
    singleOptionsFileId = null;
}

function setSingleDefaults(actionType) {
    if (actionType === 'transcribe') {
        const provider = document.getElementById('singleTranscribeProvider');
        if (provider) provider.value = 'whisper';
        const model = document.getElementById('singleTranscribeModel');
        if (model) model.value = 'medium';
        const language = document.getElementById('singleTranscribeLanguage');
        if (language) language.value = '';
        const force = document.getElementById('singleTranscribeForce');
        if (force) force.checked = false;
        const device = document.getElementById('singleTranscribeDevice');
        if (device) device.value = 'auto';
        const compute = document.getElementById('singleTranscribeCompute');
        if (compute) compute.value = 'default';
        updateTranscribeProviderUI('single');
        return;
    }

    if (actionType === 'nova') {
        const model = document.getElementById('singleNovaModel');
        if (model) model.value = 'lite';
        const processingMode = document.getElementById('singleNovaProcessingMode');
        if (processingMode) processingMode.value = 'realtime';
        const depth = document.getElementById('singleNovaSummaryDepth');
        if (depth) depth.value = 'standard';
        const language = document.getElementById('singleNovaLanguage');
        if (language) language.value = 'auto';
        const summary = document.getElementById('singleNovaSummary');
        const chapters = document.getElementById('singleNovaChapters');
        const elements = document.getElementById('singleNovaElements');
        if (summary) summary.checked = true;
        if (chapters) chapters.checked = true;
        if (elements) elements.checked = false;
        return;
    }

    if (actionType === 'rekognition') {
        const label = document.getElementById('singleRekognitionLabels');
        const faces = document.getElementById('singleRekognitionFaces');
        const celebs = document.getElementById('singleRekognitionCelebrities');
        const mod = document.getElementById('singleRekognitionModeration');
        const text = document.getElementById('singleRekognitionText');
        const persons = document.getElementById('singleRekognitionPersons');
        const shots = document.getElementById('singleRekognitionShots');
        const ppe = document.getElementById('singleRekognitionPPE');
        if (label) label.checked = true;
        if (faces) faces.checked = false;
        if (celebs) celebs.checked = false;
        if (mod) mod.checked = false;
        if (text) text.checked = false;
        if (persons) persons.checked = false;
        if (shots) shots.checked = false;
        if (ppe) ppe.checked = false;
        const useProxy = document.getElementById('singleRekognitionUseProxy');
        if (useProxy) useProxy.checked = true;
    }
}

function buildSingleOptions(actionType) {
    const errorEl = document.getElementById('singleOptionsError');
    if (errorEl) {
        errorEl.classList.add('d-none');
    }

    switch (actionType) {
        case 'transcribe': {
            const provider = document.getElementById('singleTranscribeProvider')?.value || 'whisper';
            const model = document.getElementById('singleTranscribeModel')?.value || 'medium';
            const language = document.getElementById('singleTranscribeLanguage')?.value.trim();
            const force = !!document.getElementById('singleTranscribeForce')?.checked;
            const device = document.getElementById('singleTranscribeDevice')?.value || 'auto';
            const computeType = document.getElementById('singleTranscribeCompute')?.value || 'default';
            return {
                provider: provider,
                model_size: model,
                language: language || undefined,
                force: force,
                device: device,
                compute_type: computeType
            };
        }
        case 'nova': {
            const model = document.getElementById('singleNovaModel')?.value || 'lite';
            const analysisTypes = Array.from(document.querySelectorAll('.single-nova-type:checked'))
                .map(input => input.value);
            if (analysisTypes.length === 0) {
                showSingleOptionsError('Select at least one Nova analysis type.');
                return null;
            }
            const processingMode = document.getElementById('singleNovaProcessingMode')?.value || 'realtime';
            const options = {
                summary_depth: document.getElementById('singleNovaSummaryDepth')?.value || 'standard',
                language: document.getElementById('singleNovaLanguage')?.value || 'auto'
            };
            return {
                model: model,
                analysis_types: analysisTypes,
                options: options,
                processing_mode: processingMode
            };
        }
        case 'rekognition': {
            const analysisTypes = Array.from(document.querySelectorAll('.single-rekognition-type:checked'))
                .map(input => input.value);
            if (analysisTypes.length === 0) {
                showSingleOptionsError('Select at least one Rekognition analysis type.');
                return null;
            }
            const useProxy = !!document.getElementById('singleRekognitionUseProxy')?.checked;
            return {
                analysis_types: analysisTypes,
                use_proxy: useProxy
            };
        }
        default:
            return null;
    }
}

function showSingleOptionsError(message) {
    const errorEl = document.getElementById('singleOptionsError');
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.classList.remove('d-none');
}

function showBatchOptionsError(message) {
    const errorEl = document.getElementById('batchOptionsError');
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.classList.remove('d-none');
}

async function loadNovaModels() {
    if (novaModelsLoaded) return;
    const modelSelects = [
        document.getElementById('batchNovaModel'),
        document.getElementById('singleNovaModel')
    ].filter(Boolean);
    if (modelSelects.length === 0) return;

    try {
        const response = await fetch('/api/nova/models');
        if (!response.ok) {
            throw new Error('Failed to load Nova models');
        }
        const data = await response.json();
        if (!data.models || data.models.length === 0) {
            return;
        }

        modelSelects.forEach(modelSelect => {
            modelSelect.innerHTML = '';
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model.id;
                option.textContent = model.name;
                modelSelect.appendChild(option);
            });

            const defaultOption = modelSelect.querySelector('option[value="lite"]');
            if (defaultOption) {
                defaultOption.selected = true;
            }
        });
        novaModelsLoaded = true;
    } catch (error) {
        console.warn('Failed to load Nova models:', error);
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
        document.getElementById('batchTotal').textContent = data.total_files;
        document.getElementById('batchCompleted').textContent = data.completed_files;
        document.getElementById('batchFailed').textContent = data.failed_files;
        document.getElementById('batchElapsed').textContent = formatDuration(data.elapsed_seconds);
    }

    // Detailed statistics (for transcription jobs)
    const detailedStatsDiv = document.getElementById('batchDetailedStats');
    if (currentBatchActionType === 'transcribe' && (data.status === 'RUNNING' || data.status === 'COMPLETED')) {
        // Show detailed stats
        detailedStatsDiv.style.display = 'flex';

        // Average size (all files)
        if (data.avg_video_size_total !== undefined && data.avg_video_size_total !== null) {
            document.getElementById('batchAvgSizeTotal').textContent = formatFileSize(data.avg_video_size_total);
        }

        // Average size (processed files)
        if (data.avg_video_size_processed !== undefined && data.avg_video_size_processed !== null) {
            document.getElementById('batchAvgSizeProcessed').textContent = formatFileSize(data.avg_video_size_processed);
        }

        // Calculate average time per file
        if (data.completed_files > 0 && data.elapsed_seconds) {
            const avgTime = data.elapsed_seconds / data.completed_files;
            document.getElementById('batchAvgTime').textContent = `${avgTime.toFixed(1)}s`;

            // Calculate ETA
            const remainingFiles = data.total_files - data.completed_files - data.failed_files;
            if (remainingFiles > 0 && data.status === 'RUNNING') {
                const eta = avgTime * remainingFiles;
                document.getElementById('batchETA').textContent = formatDuration(eta);
            } else {
                document.getElementById('batchETA').textContent = '-';
            }
        } else {
            document.getElementById('batchAvgTime').textContent = '-';
            document.getElementById('batchETA').textContent = '-';
        }
    } else {
        // Hide detailed stats for non-transcription jobs
        detailedStatsDiv.style.display = 'none';
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
    currentBatchActionType = null;  // Reset action type
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

// ============================================================================
// URL PARAMETER HANDLING (for search result navigation)
// ============================================================================

function handleURLParameters() {
    const params = new URLSearchParams(window.location.search);

    // Check for file ID parameter
    const fileId = params.get('id');
    if (fileId) {
        console.log('Auto-opening file details for ID:', fileId);
        viewFileDetails(parseInt(fileId));
        return;
    }

    // Check for transcript highlight parameter (format: transcript_123)
    const highlight = params.get('highlight');
    if (highlight && highlight.startsWith('transcript_')) {
        const transcriptId = parseInt(highlight.replace('transcript_', ''));
        console.log('Auto-opening transcript details for ID:', transcriptId);
        openTranscriptDetails(transcriptId);
        return;
    }

    // Check for job_id parameter (Rekognition analysis)
    const jobId = params.get('job_id');
    if (jobId) {
        console.log('Auto-opening Rekognition job details for ID:', jobId);
        // For Rekognition jobs, we need to find the file that has this job
        // and show the file details which includes analysis jobs
        findAndShowFileByJobId(parseInt(jobId));
        return;
    }

    // Check for nova_id parameter (Nova analysis)
    const novaId = params.get('nova_id');
    if (novaId) {
        console.log('Auto-opening Nova analysis details for ID:', novaId);
        // Similar to Rekognition, find the file with this Nova job
        findAndShowFileByNovaId(parseInt(novaId));
        return;
    }
}

async function findAndShowFileByJobId(jobId) {
    try {
        // Get job details to find the file_id
        const response = await fetch(`/api/history/${jobId}`);
        if (!response.ok) {
            throw new Error('Failed to load job details');
        }

        const job = await response.json();
        if (job.file_id) {
            viewFileDetails(job.file_id);
        } else {
            showAlert('Could not find file for this analysis job', 'warning');
        }
    } catch (error) {
        console.error('Failed to find file by job ID:', error);
        showAlert(`Failed to open analysis: ${error.message}`, 'danger');
    }
}

async function findAndShowFileByNovaId(novaId) {
    try {
        // Get Nova job details to find the file_id
        const response = await fetch(`/api/nova/results/${novaId}`);
        if (!response.ok) {
            throw new Error('Failed to load Nova job details');
        }

        const novaJob = await response.json();
        // Nova jobs link to analysis_job_id, need to get that first
        if (novaJob.analysis_job_id) {
            const jobResponse = await fetch(`/api/history/${novaJob.analysis_job_id}`);
            if (!jobResponse.ok) {
                throw new Error('Failed to load analysis job details');
            }
            const job = await jobResponse.json();
            if (job.file_id) {
                viewFileDetails(job.file_id);
            } else {
                showAlert('Could not find file for this Nova analysis', 'warning');
            }
        } else {
            showAlert('Could not find file for this Nova analysis', 'warning');
        }
    } catch (error) {
        console.error('Failed to find file by Nova ID:', error);
        showAlert(`Failed to open Nova analysis: ${error.message}`, 'danger');
    }
}
