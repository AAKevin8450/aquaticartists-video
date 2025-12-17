/**
 * Utility functions for AWS Video & Image Analysis App
 */

/**
 * Show alert message to user
 * @param {string} message - The message to display
 * @param {string} type - Alert type: success, danger, warning, info
 * @param {number} duration - Duration in milliseconds (default: 5000)
 */
export function showAlert(message, type = 'info', duration = 5000) {
    const alertContainer = document.getElementById('alert-container');
    if (!alertContainer) {
        console.error('Alert container not found');
        return;
    }

    const alertId = `alert-${Date.now()}`;
    const alert = document.createElement('div');
    alert.id = alertId;
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.setAttribute('role', 'alert');

    const icons = {
        success: 'check-circle',
        danger: 'exclamation-triangle',
        warning: 'exclamation-triangle',
        info: 'info-circle'
    };

    const icon = icons[type] || 'info-circle';

    alert.innerHTML = `
        <i class="bi bi-${icon}"></i>
        <strong>${message}</strong>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    alertContainer.appendChild(alert);

    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => {
            const alertElement = document.getElementById(alertId);
            if (alertElement) {
                const bsAlert = new bootstrap.Alert(alertElement);
                bsAlert.close();
            }
        }, duration);
    }
}

/**
 * Format bytes to human readable size
 * @param {number} bytes - Size in bytes
 * @param {number} decimals - Number of decimal places
 * @returns {string} Formatted size string
 */
export function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

/**
 * Format date to local string
 * @param {string|Date} date - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(date) {
    if (!date) return 'N/A';

    const d = new Date(date);
    if (isNaN(d.getTime())) return 'Invalid Date';

    return d.toLocaleString();
}

/**
 * Debounce function to limit function calls
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
export function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @returns {Promise<void>}
 */
export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showAlert('Copied to clipboard!', 'success', 2000);
    } catch (err) {
        console.error('Failed to copy:', err);
        showAlert('Failed to copy to clipboard', 'danger');
    }
}

/**
 * Validate file type
 * @param {File} file - File to validate
 * @param {string[]} allowedTypes - Array of allowed MIME types
 * @returns {boolean} True if valid
 */
export function validateFileType(file, allowedTypes) {
    if (!file) return false;
    return allowedTypes.some(type => {
        if (type.endsWith('/*')) {
            const prefix = type.slice(0, -2);
            return file.type.startsWith(prefix);
        }
        return file.type === type;
    });
}

/**
 * Validate file size
 * @param {File} file - File to validate
 * @param {number} maxSizeBytes - Maximum size in bytes
 * @returns {boolean} True if valid
 */
export function validateFileSize(file, maxSizeBytes) {
    if (!file) return false;
    return file.size <= maxSizeBytes;
}

/**
 * Get file extension from filename
 * @param {string} filename - Filename to parse
 * @returns {string} File extension (lowercase)
 */
export function getFileExtension(filename) {
    if (!filename) return '';
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

/**
 * Check if file is video
 * @param {string} filename - Filename to check
 * @returns {boolean} True if video file
 */
export function isVideoFile(filename) {
    const videoExts = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'wmv'];
    return videoExts.includes(getFileExtension(filename));
}

/**
 * Check if file is image
 * @param {string} filename - Filename to check
 * @returns {boolean} True if image file
 */
export function isImageFile(filename) {
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'];
    return imageExts.includes(getFileExtension(filename));
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Parse query parameters from URL
 * @returns {Object} Query parameters as key-value pairs
 */
export function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    const result = {};
    for (const [key, value] of params) {
        result[key] = value;
    }
    return result;
}

/**
 * Update URL query parameters without reload
 * @param {Object} params - Parameters to update
 */
export function updateQueryParams(params) {
    const url = new URL(window.location);
    Object.keys(params).forEach(key => {
        if (params[key] === null || params[key] === undefined) {
            url.searchParams.delete(key);
        } else {
            url.searchParams.set(key, params[key]);
        }
    });
    window.history.pushState({}, '', url);
}

/**
 * Fetch with timeout
 * @param {string} url - URL to fetch
 * @param {Object} options - Fetch options
 * @param {number} timeout - Timeout in milliseconds (default: 30000)
 * @returns {Promise<Response>}
 */
export async function fetchWithTimeout(url, options = {}, timeout = 30000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });
        clearTimeout(id);
        return response;
    } catch (error) {
        clearTimeout(id);
        throw error;
    }
}

/**
 * Format analysis type to human readable
 * @param {string} analysisType - Analysis type key
 * @returns {string} Formatted analysis type
 */
export function formatAnalysisType(analysisType) {
    const types = {
        'label_detection': 'Label Detection',
        'face_detection': 'Face Detection',
        'celebrity_recognition': 'Celebrity Recognition',
        'content_moderation': 'Content Moderation',
        'text_detection': 'Text Detection',
        'person_tracking': 'Person Tracking',
        'face_search': 'Face Search',
        'shot_segmentation': 'Shot/Segment Detection',
        'ppe_detection': 'PPE Detection',
        'face_comparison': 'Face Comparison'
    };
    return types[analysisType] || analysisType;
}

/**
 * Get status badge class
 * @param {string} status - Job status
 * @returns {string} Bootstrap badge class
 */
export function getStatusBadgeClass(status) {
    const classes = {
        'COMPLETED': 'bg-success',
        'FAILED': 'bg-danger',
        'IN_PROGRESS': 'bg-warning',
        'PENDING': 'bg-secondary'
    };
    return classes[status] || 'bg-secondary';
}

/**
 * Initialize tooltips (Bootstrap)
 */
export function initTooltips() {
    const tooltipTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    tooltipTriggerList.map(tooltipTriggerEl => {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * Initialize popovers (Bootstrap)
 */
export function initPopovers() {
    const popoverTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="popover"]')
    );
    popoverTriggerList.map(popoverTriggerEl => {
        return new bootstrap.Popover(popoverTriggerEl);
    });
}

// Export all functions as default object
export default {
    showAlert,
    formatBytes,
    formatDate,
    debounce,
    copyToClipboard,
    validateFileType,
    validateFileSize,
    getFileExtension,
    isVideoFile,
    isImageFile,
    escapeHtml,
    getQueryParams,
    updateQueryParams,
    fetchWithTimeout,
    formatAnalysisType,
    getStatusBadgeClass,
    initTooltips,
    initPopovers
};
