/**
 * Dashboard functionality for AWS Video Analysis Results
 */

import { showAlert } from './utils.js';

// Global state
let jobData = null;
let processedData = null;
let charts = {};
let currentSortField = 'time';
let currentSortOrder = 'asc';

/**
 * Initialize dashboard with job data
 * @param {string} jobId - Job ID to load
 */
export async function initDashboard(jobId) {
    try {
        // Fetch job data
        const response = await fetch(`/api/history/${jobId}`);
        if (!response.ok) {
            throw new Error('Failed to load job data');
        }

        jobData = await response.json();

        // Check if job is completed
        if (jobData.status !== 'SUCCEEDED' && jobData.status !== 'COMPLETED') {
            showError(`Job status: ${jobData.status}. Dashboard only available for completed jobs.`);
            return;
        }

        // Update header subtitle
        document.getElementById('dashboardSubtitle').textContent =
            `${jobData.analysis_type_display} - ${jobData.file_name}`;

        // Process data based on analysis type
        processedData = processJobData(jobData);

        // Render dashboard
        renderDashboard();

        // Hide loading, show content
        document.getElementById('loadingState').classList.add('d-none');
        document.getElementById('dashboardContent').classList.remove('d-none');

    } catch (error) {
        console.error('Dashboard initialization error:', error);
        showError(error.message);
    }
}

/**
 * Process job data based on analysis type
 */
function processJobData(job) {
    const analysisType = job.analysis_type.toLowerCase();
    const results = job.results || [];

    if (analysisType.includes('label')) {
        return processLabelData(results, job);
    } else if (analysisType.includes('face') && !analysisType.includes('search')) {
        return processFaceData(results, job);
    } else if (analysisType.includes('celebrity')) {
        return processCelebrityData(results, job);
    } else if (analysisType.includes('text')) {
        return processTextData(results, job);
    } else if (analysisType.includes('moderation')) {
        return processModerationData(results, job);
    } else if (analysisType.includes('person')) {
        return processPersonData(results, job);
    } else if (analysisType.includes('segment')) {
        return processSegmentData(results, job);
    } else if (analysisType.includes('face_search')) {
        return processFaceSearchData(results, job);
    } else {
        return processGenericData(results, job);
    }
}

/**
 * Process Label Detection data
 */
function processLabelData(results, job) {
    const labels = {};
    const timeline = [];
    let totalConfidence = 0;
    let count = 0;

    results.forEach(item => {
        const timestamp = item.Timestamp / 1000; // Convert to seconds
        const label = item.Label || {};
        const name = label.Name || 'Unknown';
        const confidence = label.Confidence || 0;

        // Aggregate labels
        if (!labels[name]) {
            labels[name] = {
                name: name,
                count: 0,
                maxConfidence: 0,
                categories: label.Categories || []
            };
        }
        labels[name].count++;
        labels[name].maxConfidence = Math.max(labels[name].maxConfidence, confidence);

        // Timeline data
        timeline.push({ timestamp, name, confidence });

        totalConfidence += confidence;
        count++;
    });

    // Sort labels by count
    const topLabels = Object.values(labels)
        .sort((a, b) => b.count - a.count)
        .slice(0, 10);

    return {
        type: 'label_detection',
        totalDetections: results.length,
        avgConfidence: count > 0 ? totalConfidence / count : 0,
        topItems: topLabels,
        timeline: timeline,
        tableData: results.map(item => ({
            timestamp: (item.Timestamp / 1000).toFixed(2),
            label: item.Label?.Name || 'Unknown',
            confidence: (item.Label?.Confidence || 0).toFixed(2),
            categories: (item.Label?.Categories || []).map(c => c.Name).join(', '),
            instances: (item.Label?.Instances || []).length
        })),
        chartData: {
            distribution: topLabels.map(l => ({ label: l.name, value: l.count })),
            confidence: aggregateConfidenceRanges(results.map(r => r.Label?.Confidence || 0))
        }
    };
}

/**
 * Process Face Detection data
 */
function processFaceData(results, job) {
    const emotions = {};
    const ageGroups = { '0-20': 0, '21-40': 0, '41-60': 0, '61+': 0 };
    const genders = { Male: 0, Female: 0 };
    let totalConfidence = 0;

    results.forEach(item => {
        const face = item.Face || {};
        const confidence = face.Confidence || 0;
        totalConfidence += confidence;

        // Aggregate emotions
        (face.Emotions || []).forEach(emotion => {
            const type = emotion.Type || 'Unknown';
            if (!emotions[type]) emotions[type] = 0;
            emotions[type] += emotion.Confidence || 0;
        });

        // Age groups
        const ageRange = face.AgeRange || {};
        const avgAge = ((ageRange.Low || 0) + (ageRange.High || 0)) / 2;
        if (avgAge <= 20) ageGroups['0-20']++;
        else if (avgAge <= 40) ageGroups['21-40']++;
        else if (avgAge <= 60) ageGroups['41-60']++;
        else ageGroups['61+']++;

        // Genders
        const gender = face.Gender?.Value || 'Unknown';
        if (gender === 'Male' || gender === 'Female') {
            genders[gender]++;
        }
    });

    // Top emotions
    const topEmotions = Object.entries(emotions)
        .map(([name, confidence]) => ({ name, confidence: confidence / results.length }))
        .sort((a, b) => b.confidence - a.confidence)
        .slice(0, 5);

    return {
        type: 'face_detection',
        totalDetections: results.length,
        avgConfidence: results.length > 0 ? totalConfidence / results.length : 0,
        topItems: topEmotions,
        timeline: results.map(item => ({
            timestamp: item.Timestamp / 1000,
            confidence: item.Face?.Confidence || 0
        })),
        tableData: results.map(item => {
            const face = item.Face || {};
            const ageRange = face.AgeRange || {};
            return {
                timestamp: (item.Timestamp / 1000).toFixed(2),
                confidence: (face.Confidence || 0).toFixed(2),
                age: `${ageRange.Low || 'N/A'}-${ageRange.High || 'N/A'}`,
                gender: `${face.Gender?.Value || 'N/A'} (${(face.Gender?.Confidence || 0).toFixed(1)}%)`,
                emotions: (face.Emotions || [])
                    .slice(0, 2)
                    .map(e => `${e.Type} (${e.Confidence.toFixed(1)}%)`)
                    .join(', ')
            };
        }),
        chartData: {
            distribution: Object.entries(ageGroups).map(([label, value]) => ({ label, value })),
            confidence: topEmotions.map(e => ({ label: e.name, value: e.confidence }))
        }
    };
}

/**
 * Process Celebrity Recognition data
 */
function processCelebrityData(results, job) {
    const celebrities = {};
    let totalConfidence = 0;

    results.forEach(item => {
        const celebrity = item.Celebrity || {};
        const name = celebrity.Name || 'Unknown';
        const confidence = celebrity.Confidence || 0;

        if (!celebrities[name]) {
            celebrities[name] = {
                name: name,
                count: 0,
                maxConfidence: 0,
                urls: celebrity.Urls || []
            };
        }
        celebrities[name].count++;
        celebrities[name].maxConfidence = Math.max(celebrities[name].maxConfidence, confidence);

        totalConfidence += confidence;
    });

    const topCelebrities = Object.values(celebrities)
        .sort((a, b) => b.maxConfidence - a.maxConfidence)
        .slice(0, 10);

    return {
        type: 'celebrity_recognition',
        totalDetections: results.length,
        avgConfidence: results.length > 0 ? totalConfidence / results.length : 0,
        topItems: topCelebrities,
        timeline: results.map(item => ({
            timestamp: item.Timestamp / 1000,
            name: item.Celebrity?.Name || 'Unknown',
            confidence: item.Celebrity?.Confidence || 0
        })),
        tableData: results.map(item => {
            const celebrity = item.Celebrity || {};
            return {
                timestamp: (item.Timestamp / 1000).toFixed(2),
                name: celebrity.Name || 'Unknown',
                confidence: (celebrity.Confidence || 0).toFixed(2),
                matchConfidence: (celebrity.MatchConfidence || 0).toFixed(2),
                urls: (celebrity.Urls || []).join(', ')
            };
        }),
        chartData: {
            distribution: topCelebrities.map(c => ({ label: c.name, value: c.count })),
            confidence: aggregateConfidenceRanges(results.map(r => r.Celebrity?.Confidence || 0))
        }
    };
}

/**
 * Process Text Detection data
 */
function processTextData(results, job) {
    const textItems = {};
    let totalConfidence = 0;

    results.forEach(item => {
        const textDetection = item.TextDetection || {};
        const text = textDetection.DetectedText || '';
        const confidence = textDetection.Confidence || 0;

        if (text && !textItems[text]) {
            textItems[text] = {
                text: text,
                count: 1,
                confidence: confidence,
                type: textDetection.Type || 'WORD'
            };
        } else if (text) {
            textItems[text].count++;
        }

        totalConfidence += confidence;
    });

    const topText = Object.values(textItems)
        .sort((a, b) => b.confidence - a.confidence)
        .slice(0, 20);

    return {
        type: 'text_detection',
        totalDetections: results.length,
        avgConfidence: results.length > 0 ? totalConfidence / results.length : 0,
        topItems: topText,
        timeline: results.map(item => ({
            timestamp: item.Timestamp / 1000,
            text: item.TextDetection?.DetectedText || '',
            confidence: item.TextDetection?.Confidence || 0
        })),
        tableData: results.map(item => {
            const textDetection = item.TextDetection || {};
            return {
                timestamp: (item.Timestamp / 1000).toFixed(2),
                text: textDetection.DetectedText || '',
                confidence: (textDetection.Confidence || 0).toFixed(2),
                type: textDetection.Type || 'WORD'
            };
        }),
        chartData: {
            distribution: [
                { label: 'LINE', value: results.filter(r => r.TextDetection?.Type === 'LINE').length },
                { label: 'WORD', value: results.filter(r => r.TextDetection?.Type === 'WORD').length }
            ],
            confidence: aggregateConfidenceRanges(results.map(r => r.TextDetection?.Confidence || 0))
        }
    };
}

/**
 * Process Content Moderation data
 */
function processModerationData(results, job) {
    const categories = {};
    let totalConfidence = 0;

    results.forEach(item => {
        const label = item.ModerationLabel || {};
        const name = label.Name || 'Unknown';
        const parent = label.ParentName || 'General';
        const confidence = label.Confidence || 0;

        if (!categories[parent]) {
            categories[parent] = { name: parent, count: 0, items: [] };
        }
        categories[parent].count++;
        categories[parent].items.push({ name, confidence });

        totalConfidence += confidence;
    });

    const topCategories = Object.values(categories)
        .sort((a, b) => b.count - a.count)
        .slice(0, 10);

    return {
        type: 'content_moderation',
        totalDetections: results.length,
        avgConfidence: results.length > 0 ? totalConfidence / results.length : 0,
        topItems: topCategories,
        timeline: results.map(item => ({
            timestamp: item.Timestamp / 1000,
            label: item.ModerationLabel?.Name || 'Unknown',
            confidence: item.ModerationLabel?.Confidence || 0
        })),
        tableData: results.map(item => {
            const label = item.ModerationLabel || {};
            return {
                timestamp: (item.Timestamp / 1000).toFixed(2),
                label: label.Name || 'Unknown',
                confidence: (label.Confidence || 0).toFixed(2),
                parent: label.ParentName || 'N/A'
            };
        }),
        chartData: {
            distribution: topCategories.map(c => ({ label: c.name, value: c.count })),
            confidence: aggregateConfidenceRanges(results.map(r => r.ModerationLabel?.Confidence || 0))
        }
    };
}

/**
 * Process Person Tracking data
 */
function processPersonData(results, job) {
    const persons = {};
    let totalConfidence = 0;

    results.forEach(item => {
        const person = item.Person || {};
        const index = person.Index || 0;
        const confidence = person.Confidence || 0;

        if (!persons[index]) {
            persons[index] = { index, count: 0, maxConfidence: 0 };
        }
        persons[index].count++;
        persons[index].maxConfidence = Math.max(persons[index].maxConfidence, confidence);

        totalConfidence += confidence;
    });

    const topPersons = Object.values(persons)
        .sort((a, b) => b.count - a.count)
        .slice(0, 20);

    return {
        type: 'person_tracking',
        totalDetections: results.length,
        avgConfidence: results.length > 0 ? totalConfidence / results.length : 0,
        topItems: topPersons.map(p => ({ name: `Person ${p.index}`, count: p.count, confidence: p.maxConfidence })),
        timeline: results.map(item => ({
            timestamp: item.Timestamp / 1000,
            person: item.Person?.Index || 0,
            confidence: item.Person?.Confidence || 0
        })),
        tableData: results.map(item => {
            const person = item.Person || {};
            return {
                timestamp: (item.Timestamp / 1000).toFixed(2),
                personIndex: person.Index || 'N/A',
                confidence: (person.Confidence || 0).toFixed(2)
            };
        }),
        chartData: {
            distribution: topPersons.map(p => ({ label: `Person ${p.index}`, value: p.count })),
            confidence: aggregateConfidenceRanges(results.map(r => r.Person?.Confidence || 0))
        }
    };
}

/**
 * Process Segment Detection data
 */
function processSegmentData(results, job) {
    const segmentTypes = {};
    let totalDuration = 0;

    results.forEach(item => {
        const type = item.Type || 'Unknown';
        const duration = (item.DurationMillis || 0) / 1000;

        if (!segmentTypes[type]) {
            segmentTypes[type] = { type, count: 0, totalDuration: 0 };
        }
        segmentTypes[type].count++;
        segmentTypes[type].totalDuration += duration;

        totalDuration += duration;
    });

    const topSegments = Object.values(segmentTypes)
        .sort((a, b) => b.count - a.count);

    return {
        type: 'segment_detection',
        totalDetections: results.length,
        avgConfidence: 0, // Segments don't always have confidence
        topItems: topSegments,
        timeline: results.map(item => ({
            timestamp: (item.StartTimestampMillis || 0) / 1000,
            type: item.Type || 'Unknown',
            duration: (item.DurationMillis || 0) / 1000
        })),
        tableData: results.map(item => {
            const confidence = item.TechnicalCueSegment?.Confidence ||
                             item.ShotSegment?.Confidence || 0;
            return {
                type: item.Type || 'Unknown',
                timestamp: ((item.StartTimestampMillis || 0) / 1000).toFixed(2),
                duration: ((item.DurationMillis || 0) / 1000).toFixed(2),
                confidence: confidence.toFixed(2)
            };
        }),
        chartData: {
            distribution: topSegments.map(s => ({ label: s.type, value: s.count })),
            confidence: topSegments.map(s => ({ label: s.type, value: s.totalDuration }))
        }
    };
}

/**
 * Process Face Search data
 */
function processFaceSearchData(results, job) {
    const matches = {};
    let totalConfidence = 0;
    let count = 0;

    results.forEach(item => {
        (item.MatchedFaces || []).forEach(match => {
            const faceId = match.Face?.FaceId || 'Unknown';
            const similarity = match.Similarity || 0;

            if (!matches[faceId]) {
                matches[faceId] = {
                    faceId: faceId,
                    count: 0,
                    maxSimilarity: 0
                };
            }
            matches[faceId].count++;
            matches[faceId].maxSimilarity = Math.max(matches[faceId].maxSimilarity, similarity);

            totalConfidence += similarity;
            count++;
        });
    });

    const topMatches = Object.values(matches)
        .sort((a, b) => b.maxSimilarity - a.maxSimilarity)
        .slice(0, 10);

    return {
        type: 'face_search',
        totalDetections: count,
        avgConfidence: count > 0 ? totalConfidence / count : 0,
        topItems: topMatches.map(m => ({ name: m.faceId.substring(0, 12) + '...', confidence: m.maxSimilarity })),
        timeline: [],
        tableData: results.flatMap(item =>
            (item.MatchedFaces || []).map(match => ({
                timestamp: (item.Timestamp / 1000).toFixed(2),
                faceId: match.Face?.FaceId || 'Unknown',
                similarity: (match.Similarity || 0).toFixed(2)
            }))
        ),
        chartData: {
            distribution: topMatches.map(m => ({ label: m.faceId.substring(0, 12), value: m.count })),
            confidence: aggregateConfidenceRanges(topMatches.map(m => m.maxSimilarity))
        }
    };
}

/**
 * Process generic data for unknown analysis types
 */
function processGenericData(results, job) {
    return {
        type: 'generic',
        totalDetections: results.length,
        avgConfidence: 0,
        topItems: [],
        timeline: [],
        tableData: results.map((item, idx) => ({
            index: idx + 1,
            timestamp: ((item.Timestamp || 0) / 1000).toFixed(2),
            data: JSON.stringify(item).substring(0, 100) + '...'
        })),
        chartData: {
            distribution: [],
            confidence: []
        }
    };
}

/**
 * Aggregate confidence values into ranges
 */
function aggregateConfidenceRanges(confidences) {
    const ranges = {
        '0-20%': 0,
        '21-40%': 0,
        '41-60%': 0,
        '61-80%': 0,
        '81-100%': 0
    };

    confidences.forEach(conf => {
        if (conf <= 20) ranges['0-20%']++;
        else if (conf <= 40) ranges['21-40%']++;
        else if (conf <= 60) ranges['41-60%']++;
        else if (conf <= 80) ranges['61-80%']++;
        else ranges['81-100%']++;
    });

    return Object.entries(ranges).map(([label, value]) => ({ label, value }));
}

/**
 * Render complete dashboard
 */
function renderDashboard() {
    renderStats();
    renderTopItems();
    renderCharts();
    renderTable();
}

/**
 * Render statistics cards
 */
function renderStats() {
    document.getElementById('statTotalDetections').textContent = processedData.totalDetections;
    document.getElementById('statAvgConfidence').textContent = processedData.avgConfidence.toFixed(1) + '%';

    // Calculate duration from job timestamps
    if (jobData.started_at && jobData.completed_at) {
        const start = new Date(jobData.started_at);
        const end = new Date(jobData.completed_at);
        const diffSeconds = Math.floor((end - start) / 1000);
        const minutes = Math.floor(diffSeconds / 60);
        const seconds = diffSeconds % 60;
        document.getElementById('statProcessingTime').textContent =
            minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
    }

    // Try to get video duration from results metadata
    // Note: VideoMetadata can be a dict or list depending on analysis type (AWS API quirk)
    if (jobData.results && jobData.results.VideoMetadata) {
        let metadata = jobData.results.VideoMetadata;

        // Handle case where VideoMetadata is a list (e.g., segment detection)
        if (Array.isArray(metadata) && metadata.length > 0) {
            metadata = metadata[0];
        }

        if (metadata.DurationMillis) {
            const totalSeconds = Math.floor(metadata.DurationMillis / 1000);
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            document.getElementById('statDuration').textContent =
                minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
        }
    }
}

/**
 * Render top detected items
 */
function renderTopItems() {
    const container = document.getElementById('topItemsContent');

    if (processedData.topItems.length === 0) {
        container.innerHTML = '<p class="text-muted">No items detected</p>';
        return;
    }

    let html = '<div class="row">';

    processedData.topItems.forEach((item, idx) => {
        const name = item.name || item.text || item.type || `Item ${idx + 1}`;
        const value = item.confidence || item.maxConfidence || item.count || 0;
        const isCount = !item.confidence && !item.maxConfidence;

        html += `
            <div class="col-md-6 mb-2">
                <div class="top-item">
                    <div>
                        <strong>${escapeHtml(name)}</strong>
                        <br>
                        <small class="text-muted">${isCount ? value + ' occurrences' : value.toFixed(1) + '% confidence'}</small>
                    </div>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: ${isCount ? (value / processedData.topItems[0].count * 100) : value}%"></div>
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

/**
 * Render charts
 */
function renderCharts() {
    // Destroy existing charts
    Object.values(charts).forEach(chart => {
        if (chart) chart.destroy();
    });

    // Distribution chart (bar chart)
    const distCtx = document.getElementById('distributionChart');
    if (distCtx && processedData.chartData.distribution.length > 0) {
        charts.distribution = new Chart(distCtx, {
            type: 'bar',
            data: {
                labels: processedData.chartData.distribution.map(d => d.label),
                datasets: [{
                    label: 'Count',
                    data: processedData.chartData.distribution.map(d => d.value),
                    backgroundColor: 'rgba(102, 126, 234, 0.8)',
                    borderColor: 'rgba(102, 126, 234, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1 }
                    }
                }
            }
        });
    }

    // Confidence chart (doughnut chart)
    const confCtx = document.getElementById('confidenceChart');
    if (confCtx && processedData.chartData.confidence.length > 0) {
        charts.confidence = new Chart(confCtx, {
            type: 'doughnut',
            data: {
                labels: processedData.chartData.confidence.map(d => d.label),
                datasets: [{
                    data: processedData.chartData.confidence.map(d => d.value),
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.8)',
                        'rgba(54, 162, 235, 0.8)',
                        'rgba(255, 206, 86, 0.8)',
                        'rgba(75, 192, 192, 0.8)',
                        'rgba(153, 102, 255, 0.8)',
                        'rgba(255, 159, 64, 0.8)'
                    ],
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    // Timeline chart (line chart)
    const timelineCtx = document.getElementById('timelineChart');
    if (timelineCtx && processedData.timeline.length > 0) {
        // Group timeline data into buckets
        const buckets = groupTimelineData(processedData.timeline);

        charts.timeline = new Chart(timelineCtx, {
            type: 'line',
            data: {
                labels: buckets.map(b => b.time + 's'),
                datasets: [{
                    label: 'Detections',
                    data: buckets.map(b => b.count),
                    borderColor: 'rgba(102, 126, 234, 1)',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Time (seconds)'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1 },
                        title: {
                            display: true,
                            text: 'Detection Count'
                        }
                    }
                }
            }
        });
    }
}

/**
 * Group timeline data into time buckets
 */
function groupTimelineData(timeline) {
    if (timeline.length === 0) return [];

    const maxTime = Math.max(...timeline.map(t => t.timestamp));
    const bucketSize = Math.max(1, Math.floor(maxTime / 50)); // ~50 buckets
    const buckets = [];

    for (let i = 0; i <= maxTime; i += bucketSize) {
        const count = timeline.filter(t => t.timestamp >= i && t.timestamp < i + bucketSize).length;
        buckets.push({ time: i, count });
    }

    return buckets;
}

/**
 * Render data table
 */
function renderTable() {
    const tableHeaders = document.getElementById('tableHeaders');
    const tableBody = document.getElementById('tableBody');

    if (processedData.tableData.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="100" class="text-center text-muted">No data available</td></tr>';
        return;
    }

    // Generate headers from first row keys
    const headers = Object.keys(processedData.tableData[0]);
    tableHeaders.innerHTML = headers.map(h =>
        `<th>${h.charAt(0).toUpperCase() + h.slice(1)}</th>`
    ).join('');

    // Generate rows
    renderTableRows(processedData.tableData);
}

/**
 * Render table rows
 */
function renderTableRows(data) {
    const tableBody = document.getElementById('tableBody');

    const html = data.map(row => {
        const cells = Object.values(row).map(val =>
            `<td>${escapeHtml(String(val))}</td>`
        ).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    tableBody.innerHTML = html;

    // Update row counts
    document.getElementById('displayedRows').textContent = data.length;
    document.getElementById('totalRows').textContent = processedData.tableData.length;
}

/**
 * Filter table based on search query
 */
export function filterTable(query) {
    if (!query) {
        renderTableRows(processedData.tableData);
        return;
    }

    const filtered = processedData.tableData.filter(row => {
        return Object.values(row).some(val =>
            String(val).toLowerCase().includes(query.toLowerCase())
        );
    });

    renderTableRows(filtered);
}

/**
 * Sort table by field
 */
export function sortTable(field) {
    let sortedData = [...processedData.tableData];

    if (field === 'confidence') {
        sortedData.sort((a, b) => {
            const aConf = parseFloat(a.confidence || 0);
            const bConf = parseFloat(b.confidence || 0);
            return currentSortOrder === 'asc' ? aConf - bConf : bConf - aConf;
        });
    } else if (field === 'time') {
        sortedData.sort((a, b) => {
            const aTime = parseFloat(a.timestamp || 0);
            const bTime = parseFloat(b.timestamp || 0);
            return currentSortOrder === 'asc' ? aTime - bTime : bTime - aTime;
        });
    }

    currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
    renderTableRows(sortedData);
}

/**
 * Export results
 */
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

/**
 * Show error state
 */
function showError(message) {
    document.getElementById('loadingState').classList.add('d-none');
    document.getElementById('errorState').classList.remove('d-none');
    document.getElementById('errorMessage').textContent = message;
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Export functions
export default {
    initDashboard,
    filterTable,
    sortTable,
    exportResults
};
