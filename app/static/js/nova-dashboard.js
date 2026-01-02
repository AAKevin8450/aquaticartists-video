/**
 * Nova dashboard rendering for AWS Nova analysis results.
 */

import { showAlert, escapeHtml } from './utils.js';

let jobData = null;
let novaResults = null;

export async function initNovaDashboard(jobId) {
    try {
        const response = await fetch(`/api/history/${jobId}`);
        if (!response.ok) {
            throw new Error('Failed to load job data');
        }

        jobData = await response.json();
        console.log('Received jobData:', jobData);

        if (jobData.status !== 'SUCCEEDED' && jobData.status !== 'COMPLETED') {
            showError(`Job status: ${jobData.status}. Dashboard only available for completed jobs.`);
            return;
        }

        document.getElementById('dashboardSubtitle').textContent =
            `${jobData.analysis_type_display} - ${jobData.file_name}`;

        novaResults = jobData.results || {};
        console.log('novaResults type:', typeof novaResults);
        console.log('novaResults is array?', Array.isArray(novaResults));
        console.log('novaResults keys:', Object.keys(novaResults));

        // Fetch file data to get thumbnail
        try {
            const fileResponse = await fetch(`/api/files/${jobData.file_id}`);
            if (fileResponse.ok) {
                const fileData = await fileResponse.json();
                window.proxyData = fileData.proxy || {};
                console.log('Proxy data:', window.proxyData);
            } else {
                console.warn('Failed to fetch file data for thumbnail');
                window.proxyData = {};
            }
        } catch (error) {
            console.error('Error fetching file data:', error);
            window.proxyData = {};
        }

        renderNovaDashboard();

        document.getElementById('loadingState').classList.add('d-none');
        document.getElementById('dashboardContent').classList.add('d-none');
        document.getElementById('novaDashboardContent').classList.remove('d-none');
    } catch (error) {
        console.error('Nova dashboard initialization error:', error);
        console.error('Error stack:', error.stack);
        showError(error.message);
    }
}

function renderNovaDashboard() {
    console.log('renderNovaDashboard called with novaResults:', novaResults);
    const contentType = novaResults.content_type || 'video';
    console.log('Content type:', contentType);

    renderMediaThumbnail();
    renderNovaStats();

    if (contentType === 'image') {
        renderImageDescription();
        renderWaterfallClassification();
        renderImageMetadata();
        renderElements();
    } else {
        renderSummary();
        renderWaterfallClassification();
        renderChapters();
        renderElements();
    }

    renderComparison();
}

function renderMediaThumbnail() {
    const thumbnailColumn = document.getElementById('thumbnailColumn');
    const statsColumn = document.getElementById('statsColumn');
    const thumbImg = document.getElementById('novaMediaThumbnail');
    const thumbType = document.getElementById('thumbnailType');

    const thumbnailPath = window.proxyData?.thumbnail_path;
    if (!thumbnailPath) {
        // No thumbnail available - hide column and expand stats
        thumbnailColumn.style.display = 'none';
        statsColumn.className = 'col-lg-12';
        return;
    }

    // Show thumbnail column and adjust stats column
    thumbnailColumn.style.display = '';
    statsColumn.className = 'col-lg-9';
    thumbImg.src = thumbnailPath;

    const contentType = novaResults.content_type || 'video';
    thumbType.textContent = contentType === 'image' ? 'Image Preview' : 'Video Thumbnail';

    // Click handler to open full proxy
    thumbImg.onclick = () => {
        const proxyUrl = window.proxyData?.presigned_url || window.proxyData?.local_path;
        if (proxyUrl) {
            window.open(proxyUrl, '_blank');
        }
    };
}

function renderNovaStats() {
    const totals = novaResults.totals || {};
    const tokensTotal = totals.tokens_total || 0;
    const costUsd = totals.cost_total_usd ?? 0;
    const processingTime = totals.processing_time_seconds ?? 0;

    document.getElementById('novaStatTokens').textContent = tokensTotal.toLocaleString();
    document.getElementById('novaStatCost').textContent = `$${Number(costUsd).toFixed(4)}`;
    document.getElementById('novaStatModel').textContent = (novaResults.model || '--').toUpperCase();

    const processingLabel = processingTime ? `${processingTime}s` : '--';
    document.getElementById('novaStatProcessing').textContent = processingLabel;

    const runDetails = document.getElementById('novaRunDetails');
    const analysisTypes = Array.isArray(novaResults.analysis_types)
        ? novaResults.analysis_types.join(', ')
        : '';
    const processingMode = (jobData.parameters && jobData.parameters.processing_mode) || novaResults.processing_mode;
    const options = novaResults.options || {};
    const chunked = novaResults.chunked ? 'Yes' : 'No';
    runDetails.innerHTML = `
        <div class="mb-2"><strong>Analysis Types:</strong> ${escapeHtml(analysisTypes || '--')}</div>
        <div class="mb-2"><strong>Summary Depth:</strong> ${escapeHtml(options.summary_depth || '--')}</div>
        <div class="mb-2"><strong>Language:</strong> ${escapeHtml(options.language || 'auto')}</div>
        <div class="mb-2"><strong>Processing Mode:</strong> ${escapeHtml(processingMode || 'realtime')}</div>
        <div class="mb-2"><strong>Chunked:</strong> ${chunked}</div>
    `;
}

function renderSummary() {
    const summary = novaResults.summary || null;
    const summaryContent = document.getElementById('novaSummaryContent');
    const summaryMeta = document.getElementById('novaSummaryMeta');
    const summaryCard = document.getElementById('novaSummaryContent')?.closest('.card');

    if (!summary) {
        if (summaryCard) summaryCard.style.display = 'none';
        return;
    }

    if (summaryCard) summaryCard.style.display = '';

    summaryContent.textContent = summary.text || 'No summary text returned.';

    const metaParts = [];
    if (summary.depth) metaParts.push(`Depth: ${summary.depth}`);
    if (summary.language) metaParts.push(`Language: ${summary.language}`);
    if (summary.word_count) metaParts.push(`Words: ${summary.word_count}`);

    summaryMeta.innerHTML = metaParts.length
        ? `<span class="badge bg-light text-dark me-2">${metaParts.join('</span><span class="badge bg-light text-dark me-2">')}</span>`
        : '';
}

function renderImageDescription() {
    const description = novaResults.description || null;
    const summaryContent = document.getElementById('novaSummaryContent');
    const summaryMeta = document.getElementById('novaSummaryMeta');
    const summaryCard = document.getElementById('novaSummaryContent')?.closest('.card');
    const summaryHeader = summaryCard?.querySelector('.card-header h5');

    if (!description) {
        if (summaryCard) summaryCard.style.display = 'none';
        return;
    }

    if (summaryCard) summaryCard.style.display = '';
    if (summaryHeader) summaryHeader.textContent = 'Image Description';

    // Build description text from structured fields
    let descriptionText = '';
    if (description.overview) {
        descriptionText += `Overview:\n${description.overview}\n\n`;
    }
    if (description.detailed) {
        descriptionText += `Detailed Description:\n${description.detailed}\n\n`;
    }
    if (description.scene_type) {
        descriptionText += `Scene Type: ${description.scene_type}\n`;
    }
    if (description.primary_subject) {
        descriptionText += `Primary Subject: ${description.primary_subject}\n`;
    }
    if (description.composition_notes) {
        descriptionText += `Composition: ${description.composition_notes}\n`;
    }

    summaryContent.textContent = descriptionText || 'No description available.';

    const metaParts = [];
    if (description.scene_type) metaParts.push(`Scene: ${description.scene_type}`);
    if (description.primary_subject) metaParts.push(`Subject: ${description.primary_subject}`);

    summaryMeta.innerHTML = metaParts.length
        ? `<span class="badge bg-light text-dark me-2">${metaParts.join('</span><span class="badge bg-light text-dark me-2">')}</span>`
        : '';
}

function renderImageMetadata() {
    const metadata = novaResults.metadata || null;
    const chaptersContainer = document.getElementById('novaChaptersList');
    const chaptersCard = chaptersContainer?.closest('.card');
    const chaptersHeader = chaptersCard?.querySelector('.card-header h5');

    if (!metadata) {
        if (chaptersCard) chaptersCard.style.display = 'none';
        return;
    }

    if (chaptersCard) chaptersCard.style.display = '';
    if (chaptersHeader) chaptersHeader.textContent = 'Extracted Metadata';

    // Render metadata as structured list
    let metadataHtml = '<div class="list-group list-group-flush">';

    // Date and Time
    if (metadata.date || metadata.time) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>Date & Time</strong><br>';
        if (metadata.date) metadataHtml += `Date: ${escapeHtml(metadata.date)}<br>`;
        if (metadata.time) metadataHtml += `Time: ${escapeHtml(metadata.time)}`;
        if (metadata.date_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.date_source)}</span>`;
        metadataHtml += '</div>';
    }

    // Location
    if (metadata.location || metadata.latitude || metadata.longitude) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>Location</strong><br>';
        if (metadata.location) metadataHtml += `${escapeHtml(metadata.location)}<br>`;
        if (metadata.latitude && metadata.longitude) {
            metadataHtml += `GPS: ${metadata.latitude.toFixed(6)}, ${metadata.longitude.toFixed(6)}`;
            if (metadata.location_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.location_source)}</span>`;
        }
        metadataHtml += '</div>';
    }

    // People
    if (metadata.people && Array.isArray(metadata.people) && metadata.people.length > 0) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>People</strong><br>';
        metadataHtml += metadata.people.map(p => escapeHtml(p)).join(', ');
        if (metadata.people_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.people_source)}</span>`;
        metadataHtml += '</div>';
    }

    // Objects/Subjects
    if (metadata.objects && Array.isArray(metadata.objects) && metadata.objects.length > 0) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>Objects</strong><br>';
        metadataHtml += metadata.objects.map(o => escapeHtml(o)).join(', ');
        if (metadata.objects_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.objects_source)}</span>`;
        metadataHtml += '</div>';
    }

    // Activities/Actions
    if (metadata.activities && Array.isArray(metadata.activities) && metadata.activities.length > 0) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>Activities</strong><br>';
        metadataHtml += metadata.activities.map(a => escapeHtml(a)).join(', ');
        if (metadata.activities_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.activities_source)}</span>`;
        metadataHtml += '</div>';
    }

    // Environment/Setting
    if (metadata.environment) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += `<strong>Environment:</strong> ${escapeHtml(metadata.environment)}`;
        if (metadata.environment_source) metadataHtml += ` <span class="badge bg-info text-dark">${escapeHtml(metadata.environment_source)}</span>`;
        metadataHtml += '</div>';
    }

    // Tags
    if (metadata.tags && Array.isArray(metadata.tags) && metadata.tags.length > 0) {
        metadataHtml += '<div class="list-group-item">';
        metadataHtml += '<strong>Tags</strong><br>';
        metadataHtml += metadata.tags.map(t => `<span class="badge bg-secondary me-1">${escapeHtml(t)}</span>`).join('');
        metadataHtml += '</div>';
    }

    metadataHtml += '</div>';

    if (metadataHtml === '<div class="list-group list-group-flush"></div>') {
        chaptersContainer.innerHTML = '<p class="text-muted">No metadata extracted.</p>';
    } else {
        chaptersContainer.innerHTML = metadataHtml;
    }
}

function renderWaterfallClassification() {
    const container = document.getElementById('novaWaterfallContent');
    if (!container) {
        return;
    }

    const classification = novaResults.waterfall_classification || null;
    if (!classification) {
        container.textContent = 'No waterfall classification available.';
        return;
    }

    const fields = [
        { label: 'Family', value: classification.family },
        { label: 'Functional Type', value: classification.functional_type },
        { label: 'Tier Level', value: classification.tier_level },
        { label: 'Sub-Type', value: classification.sub_type }
    ];

    const confidence = classification.confidence || {};
    const evidence = classification.evidence || [];
    const unknownReasons = classification.unknown_reasons || {};

    const fieldRows = fields.map(field => `
        <div class="mb-2"><strong>${escapeHtml(field.label)}:</strong> ${escapeHtml(field.value || '--')}</div>
    `).join('');

    const confidenceRow = `
        <div class="mb-2"><strong>Overall Confidence:</strong> ${confidence.overall != null ? Number(confidence.overall).toFixed(2) : '--'}</div>
    `;

    const evidenceList = Array.isArray(evidence) && evidence.length
        ? `<div class="mb-2"><strong>Evidence:</strong> ${escapeHtml(evidence.join(', '))}</div>`
        : '';

    const unknownEntries = Object.entries(unknownReasons).filter(([, value]) => value);
    const unknownList = unknownEntries.length
        ? `<div class="mb-2"><strong>Unknown Reasons:</strong> ${unknownEntries.map(([key, value]) => `${escapeHtml(key)}: ${escapeHtml(value)}`).join('; ')}</div>`
        : '';

    container.innerHTML = `${fieldRows}${confidenceRow}${evidenceList}${unknownList}`;
}

function renderChapters() {
    const chaptersContainer = document.getElementById('novaChaptersList');
    const chaptersCard = chaptersContainer?.closest('.card');
    const chaptersResult = novaResults.chapters || {};
    const chapters = Array.isArray(chaptersResult.chapters) ? chaptersResult.chapters :
                     (Array.isArray(chaptersResult) ? chaptersResult : []);

    if (!Array.isArray(chapters) || !chapters.length) {
        if (chaptersCard) chaptersCard.style.display = 'none';
        return;
    }

    if (chaptersCard) chaptersCard.style.display = '';

    const chapterCards = chapters.map((chapter) => {
        const start = chapter.start_time || '--';
        const end = chapter.end_time || '--';
        const keyPoints = (chapter.key_points || []).slice(0, 5).map(p => `<li>${escapeHtml(p)}</li>`).join('');

        return `
            <div class="segment-item nova-chapter-card">
                <div class="segment-time">${escapeHtml(start)} - ${escapeHtml(end)}</div>
                <div class="segment-info">
                    <strong>${escapeHtml(chapter.title || 'Untitled')}</strong>
                    <div class="text-muted small">${escapeHtml(chapter.summary || '')}</div>
                    ${keyPoints ? `<ul class="small mb-0">${keyPoints}</ul>` : ''}
                </div>
                <div class="text-muted small">${chapter.duration || ''}</div>
            </div>
        `;
    }).join('');

    chaptersContainer.innerHTML = chapterCards;
}

function renderElements() {
    const elements = novaResults.elements || {};
    const contentType = novaResults.content_type || 'video';

    if (contentType === 'image') {
        renderImageElements(elements);
    } else {
        renderEquipment(elements.equipment || []);
        renderTopics(elements.topics_discussed || []);
        renderSpeakers(elements.speakers || [], elements.people || {});
    }
}

function renderImageElements(elements) {
    const tableBody = document.getElementById('novaEquipmentTable');
    const equipmentCard = tableBody?.closest('.card');
    const equipmentHeader = equipmentCard?.querySelector('.card-header h5');

    if (equipmentHeader) equipmentHeader.textContent = 'Detected Elements';

    // Build combined list of all detected elements
    const elementsList = [];

    if (elements.equipment && Array.isArray(elements.equipment) && elements.equipment.length > 0) {
        elementsList.push({
            category: 'Equipment',
            items: elements.equipment
        });
    }

    if (elements.objects && Array.isArray(elements.objects) && elements.objects.length > 0) {
        elementsList.push({
            category: 'Objects',
            items: elements.objects
        });
    }

    if (elements.structures && Array.isArray(elements.structures) && elements.structures.length > 0) {
        elementsList.push({
            category: 'Structures',
            items: elements.structures
        });
    }

    if (elements.text_visible && Array.isArray(elements.text_visible) && elements.text_visible.length > 0) {
        elementsList.push({
            category: 'Text/Labels',
            items: elements.text_visible
        });
    }

    if (elementsList.length === 0) {
        tableBody.innerHTML = '<tr><td class="text-muted">No elements detected.</td></tr>';
        return;
    }

    // Render as simplified table
    tableBody.innerHTML = elementsList.map(group => `
        <tr>
            <td><strong>${escapeHtml(group.category)}</strong></td>
            <td>${group.items.map(item => escapeHtml(item)).join(', ')}</td>
        </tr>
    `).join('');

    // Hide topics and speakers sections for images
    const topicsCard = document.getElementById('novaTopicsTable')?.closest('.card');
    const speakersCard = document.getElementById('novaSpeakersTable')?.closest('.card');
    if (topicsCard) topicsCard.style.display = 'none';
    if (speakersCard) speakersCard.style.display = 'none';

    // Show people info if available
    if (elements.people) {
        const peopleSummary = document.getElementById('novaPeopleSummary');
        if (peopleSummary) {
            peopleSummary.innerHTML = `
                <div class="mb-2"><strong>People in Image:</strong> ${elements.people.count || 0}</div>
                ${elements.people.description ? `<div class="mb-2">${escapeHtml(elements.people.description)}</div>` : ''}
            `;
        }
    }
}

function renderEquipment(equipment) {
    const tableBody = document.getElementById('novaEquipmentTable');
    const equipmentCard = tableBody?.closest('.card');

    if (!Array.isArray(equipment) || !equipment.length) {
        if (equipmentCard) equipmentCard.style.display = 'none';
        return;
    }

    if (equipmentCard) equipmentCard.style.display = '';

    tableBody.innerHTML = equipment.map(item => {
        const timeRanges = (item.time_ranges || []).join(', ');
        const discussed = item.discussed ? 'Yes' : 'No';
        return `
            <tr>
                <td>${escapeHtml(item.name || 'Unknown')}</td>
                <td>${escapeHtml(item.category || 'n/a')}</td>
                <td>${escapeHtml(timeRanges || '--')}</td>
                <td>${discussed}</td>
            </tr>
        `;
    }).join('');
}

function renderTopics(topics) {
    const tableBody = document.getElementById('novaTopicsTable');
    const topicsCard = tableBody?.closest('.card');

    if (!Array.isArray(topics) || !topics.length) {
        if (topicsCard) topicsCard.style.display = 'none';
        return;
    }

    if (topicsCard) topicsCard.style.display = '';

    tableBody.innerHTML = topics.map(topic => {
        const timeRanges = (topic.time_ranges || []).join(', ');
        return `
            <tr>
                <td>${escapeHtml(topic.topic || 'Unknown')}</td>
                <td>${escapeHtml(topic.importance || 'medium')}</td>
                <td>${escapeHtml(timeRanges || '--')}</td>
            </tr>
        `;
    }).join('');
}

function renderSpeakers(speakers, people) {
    const tableBody = document.getElementById('novaSpeakersTable');
    const speakersCard = tableBody?.closest('.card');
    const peopleSummary = document.getElementById('novaPeopleSummary');

    if (!Array.isArray(speakers) || !speakers.length) {
        if (speakersCard) speakersCard.style.display = 'none';
        return;
    }

    if (speakersCard) speakersCard.style.display = '';

    const maxCount = people?.max_count ?? 'n/a';
    const multiple = people?.multiple_speakers ? 'Yes' : 'No';
    if (peopleSummary) {
        peopleSummary.innerHTML = `
            <div class="mb-2"><strong>Max People On Screen:</strong> ${maxCount}</div>
            <div class="mb-2"><strong>Multiple Speakers:</strong> ${multiple}</div>
        `;
    }

    tableBody.innerHTML = speakers.map(speaker => {
        const share = speaker.speaking_percentage != null ? `${speaker.speaking_percentage.toFixed(1)}%` : '--';
        return `
            <tr>
                <td>${escapeHtml(speaker.speaker_id || 'Speaker')}</td>
                <td>${escapeHtml(speaker.role || 'n/a')}</td>
                <td>${share}</td>
            </tr>
        `;
    }).join('');
}

async function renderComparison() {
    const container = document.getElementById('novaComparisonList');
    container.innerHTML = '<div class="text-muted">Loading related analyses...</div>';

    try {
        const response = await fetch(`/api/history/?file_id=${jobData.file_id}`);
        if (!response.ok) {
            throw new Error('Failed to load related jobs');
        }

        const data = await response.json();
        const related = (data.jobs || []).filter(job => job.analysis_type !== 'nova');

        if (!related.length) {
            container.innerHTML = '<div class="text-muted">No related analysis jobs found for this file.</div>';
            return;
        }

        container.innerHTML = related.map(job => `
            <a href="/dashboard/${job.job_id}" class="list-group-item list-group-item-action">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${escapeHtml(job.analysis_type_display || job.analysis_type)}</strong>
                        <div class="small text-muted">Status: ${job.status}</div>
                    </div>
                    <i class="bi bi-chevron-right"></i>
                </div>
            </a>
        `).join('');
    } catch (error) {
        console.error('Failed to load comparison jobs:', error);
        container.innerHTML = '<div class="text-muted">Unable to load related analyses.</div>';
    }
}

export function exportResults(jobId, format) {
    const link = document.createElement('a');

    if (format === 'excel') {
        link.href = `/api/history/${jobId}/download?format=excel`;
        link.download = `job-${jobId}-results.xlsx`;
        showAlert('Downloading Excel file...', 'info', 2000);
    } else {
        link.href = `/api/history/${jobId}/download?format=json`;
        link.download = `job-${jobId}-results.json`;
        showAlert('Downloading JSON file...', 'info', 2000);
    }

    link.click();
}

function showError(message) {
    document.getElementById('loadingState').classList.add('d-none');
    document.getElementById('errorState').classList.remove('d-none');
    document.getElementById('errorMessage').textContent = message;
}

export default {
    initNovaDashboard,
    exportResults
};
