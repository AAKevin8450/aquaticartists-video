/**
 * Nova dashboard rendering for AWS Nova analysis results.
 */

import { showAlert } from './utils.js';

let jobData = null;
let novaResults = null;

export async function initNovaDashboard(jobId) {
    try {
        const response = await fetch(`/api/history/${jobId}`);
        if (!response.ok) {
            throw new Error('Failed to load job data');
        }

        jobData = await response.json();

        if (jobData.status !== 'SUCCEEDED' && jobData.status !== 'COMPLETED') {
            showError(`Job status: ${jobData.status}. Dashboard only available for completed jobs.`);
            return;
        }

        document.getElementById('dashboardSubtitle').textContent =
            `${jobData.analysis_type_display} - ${jobData.file_name}`;

        novaResults = jobData.results || {};

        renderNovaDashboard();

        document.getElementById('loadingState').classList.add('d-none');
        document.getElementById('dashboardContent').classList.add('d-none');
        document.getElementById('novaDashboardContent').classList.remove('d-none');
    } catch (error) {
        console.error('Nova dashboard initialization error:', error);
        showError(error.message);
    }
}

function renderNovaDashboard() {
    renderNovaStats();
    renderSummary();
    renderWaterfallClassification();
    renderChapters();
    renderElements();
    renderComparison();
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

    if (!summary) {
        summaryContent.textContent = 'No summary available.';
        summaryMeta.innerHTML = '';
        return;
    }

    summaryContent.textContent = summary.text || 'No summary text returned.';

    const metaParts = [];
    if (summary.depth) metaParts.push(`Depth: ${summary.depth}`);
    if (summary.language) metaParts.push(`Language: ${summary.language}`);
    if (summary.word_count) metaParts.push(`Words: ${summary.word_count}`);

    summaryMeta.innerHTML = metaParts.length
        ? `<span class="badge bg-light text-dark me-2">${metaParts.join('</span><span class="badge bg-light text-dark me-2">')}</span>`
        : '';
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
    const chaptersResult = novaResults.chapters || {};
    const chapters = chaptersResult.chapters || [];

    if (!chapters.length) {
        chaptersContainer.innerHTML = '<p class="text-muted">No chapters detected.</p>';
        return;
    }

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
    renderEquipment(elements.equipment || []);
    renderTopics(elements.topics_discussed || []);
    renderSpeakers(elements.speakers || [], elements.people || {});
}

function renderEquipment(equipment) {
    const tableBody = document.getElementById('novaEquipmentTable');

    if (!equipment.length) {
        tableBody.innerHTML = '<tr><td colspan="4" class="text-muted">No equipment detected.</td></tr>';
        return;
    }

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

    if (!topics.length) {
        tableBody.innerHTML = '<tr><td colspan="3" class="text-muted">No topics detected.</td></tr>';
        return;
    }

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
    const peopleSummary = document.getElementById('novaPeopleSummary');

    const maxCount = people.max_count ?? 'n/a';
    const multiple = people.multiple_speakers ? 'Yes' : 'No';
    peopleSummary.innerHTML = `
        <div class="mb-2"><strong>Max People On Screen:</strong> ${maxCount}</div>
        <div class="mb-2"><strong>Multiple Speakers:</strong> ${multiple}</div>
    `;

    if (!speakers.length) {
        tableBody.innerHTML = '<tr><td colspan="3" class="text-muted">No speakers detected.</td></tr>';
        return;
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
            container.innerHTML = '<div class="text-muted">No Rekognition jobs found for this file.</div>';
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

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

export default {
    initNovaDashboard,
    exportResults
};
