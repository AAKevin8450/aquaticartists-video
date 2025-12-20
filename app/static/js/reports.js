(() => {
    const startInput = document.getElementById('reportStart');
    const endInput = document.getElementById('reportEnd');
    const form = document.getElementById('reportFilters');
    const quickButtons = document.querySelectorAll('[data-range]');
    const rangeLabel = document.getElementById('reportRangeLabel');

    const numberFormatter = new Intl.NumberFormat();
    const currencyFormatter = new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2
    });

    const formatNumber = (value) => numberFormatter.format(value || 0);
    const formatCurrency = (value) => currencyFormatter.format(value || 0);

    const formatDuration = (seconds) => {
        const total = Math.max(0, Math.round(seconds || 0));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const secs = total % 60;
        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        }
        if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        }
        return `${secs}s`;
    };

    const formatBytes = (bytes) => {
        const value = Number(bytes || 0);
        if (value === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(value) / Math.log(k));
        return `${(value / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
    };

    const toDateInputValue = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    const setQuickRange = (days, rangeKey) => {
        const end = new Date();
        const start = new Date();
        start.setDate(end.getDate() - (days - 1));
        startInput.value = toDateInputValue(start);
        endInput.value = toDateInputValue(end);
        updateQuickActive(rangeKey);
        updateRangeLabel();
        loadReport();
    };

    const updateQuickActive = (activeKey) => {
        quickButtons.forEach((button) => {
            if (button.dataset.range === activeKey) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    };

    const updateRangeLabel = () => {
        if (startInput.value && endInput.value) {
            rangeLabel.textContent = `${startInput.value} to ${endInput.value}`;
        }
    };

    const fillTable = (tbodyId, rows, columns, emptyLabel) => {
        const tbody = document.getElementById(tbodyId);
        tbody.innerHTML = '';

        if (!rows || rows.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = columns.length;
            cell.className = 'text-center reports-muted';
            cell.textContent = emptyLabel || 'No data';
            row.appendChild(cell);
            tbody.appendChild(row);
            return;
        }

        rows.forEach((rowData) => {
            const row = document.createElement('tr');
            columns.forEach((column) => {
                const cell = document.createElement('td');
                if (column.align === 'end') {
                    cell.classList.add('text-end');
                }
                const value = rowData[column.key];
                cell.textContent = column.format ? column.format(value, rowData) : (value ?? '');
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
    };

    const renderBars = (daily, totalTokens) => {
        const container = document.getElementById('tokenBars');
        container.innerHTML = '';
        const maxTokens = daily.reduce((max, item) => Math.max(max, item.tokens_total || 0), 0);
        const floor = maxTokens === 0 ? 8 : 2;

        daily.forEach((item) => {
            const bar = document.createElement('span');
            const height = maxTokens ? Math.max(floor, Math.round((item.tokens_total / maxTokens) * 100)) : floor;
            bar.style.height = `${height}%`;
            bar.title = `${item.day}: ${formatNumber(item.tokens_total)} tokens`;
            container.appendChild(bar);
        });

        const trendTotal = document.getElementById('trendTotal');
        trendTotal.textContent = `${formatNumber(totalTokens)} total`;
    };

    const renderDailyTable = (daily) => {
        fillTable(
            'dailyRows',
            daily,
            [
                { key: 'day' },
                { key: 'tokens_total', align: 'end', format: formatNumber },
                { key: 'cost_total', align: 'end', format: formatCurrency },
                { key: 'jobs_total', align: 'end', format: formatNumber },
                { key: 'jobs_success', align: 'end', format: formatNumber },
                { key: 'jobs_failed', align: 'end', format: formatNumber }
            ],
            'No daily activity'
        );
    };

    const renderReport = (data) => {
        const tokens = data.tokens || {};
        const jobs = data.jobs || {};
        const files = data.files || {};
        const transcripts = data.transcripts || {};
        const daily = data.daily || [];

        const totalJobs = jobs.total_jobs || 0;
        const successJobs = jobs.success_jobs || 0;
        const failedJobs = jobs.failed_jobs || 0;
        const successRate = totalJobs ? Math.round((successJobs / totalJobs) * 100) : 0;

        document.getElementById('metricTokens').textContent = formatNumber(tokens.tokens_total);
        document.getElementById('metricTokensSub').textContent = `${formatNumber(tokens.tokens_input)} in / ${formatNumber(tokens.tokens_output)} out`;
        document.getElementById('metricCost').textContent = formatCurrency(tokens.cost_total);
        document.getElementById('metricFiles').textContent = formatNumber(files.processed);
        document.getElementById('metricSuccess').textContent = `${successRate}%`;

        document.getElementById('metricJobs').textContent = formatNumber(totalJobs);
        document.getElementById('metricFailures').textContent = formatNumber(failedJobs);
        document.getElementById('metricNovaJobs').textContent = formatNumber(tokens.nova_jobs);
        document.getElementById('metricAvgTime').textContent = formatDuration(tokens.avg_processing_time);
        document.getElementById('metricRunning').textContent = formatNumber(jobs.running_jobs);
        document.getElementById('metricSubmitted').textContent = formatNumber(jobs.submitted_jobs);
        document.getElementById('metricCompleted').textContent = formatNumber(successJobs);

        document.getElementById('metricUploads').textContent = formatNumber(files.files_uploaded);
        document.getElementById('metricUploadsVideo').textContent = formatNumber(files.uploaded_videos);
        document.getElementById('metricUploadsImage').textContent = formatNumber(files.uploaded_images);
        document.getElementById('metricUploadSize').textContent = formatBytes(files.upload_bytes);
        document.getElementById('metricUploadDuration').textContent = formatDuration(files.upload_duration);
        document.getElementById('metricTranscripts').textContent = `${formatNumber(transcripts.completed_transcripts)} / ${formatNumber(transcripts.total_transcripts)}`;

        renderBars(daily, tokens.tokens_total || 0);
        renderDailyTable(daily);

        fillTable(
            'fileTypeRows',
            data.file_types?.by_type || [],
            [
                { key: 'file_type' },
                { key: 'count', align: 'end', format: formatNumber }
            ],
            'No file types yet'
        );

        fillTable(
            'extensionRows',
            data.file_types?.by_extension || [],
            [
                { key: 'extension' },
                { key: 'count', align: 'end', format: formatNumber }
            ],
            'No extensions yet'
        );

        fillTable(
            'contentTypeRows',
            data.file_types?.by_content_type || [],
            [
                { key: 'content_type' },
                { key: 'count', align: 'end', format: formatNumber }
            ],
            'No content types yet'
        );

        fillTable(
            'analysisRows',
            data.analysis_types || [],
            [
                { key: 'analysis_type' },
                { key: 'count', align: 'end', format: formatNumber }
            ],
            'No analysis activity'
        );

        fillTable(
            'modelRows',
            data.nova_models || [],
            [
                { key: 'model' },
                { key: 'count', align: 'end', format: formatNumber },
                { key: 'tokens_total', align: 'end', format: formatNumber },
                { key: 'cost_total', align: 'end', format: formatCurrency }
            ],
            'No Nova model usage'
        );
    };

    const loadReport = async () => {
        updateRangeLabel();
        const start = startInput.value;
        const end = endInput.value;

        const url = new URL('/reports/api/summary', window.location.origin);
        if (start) url.searchParams.set('start', start);
        if (end) url.searchParams.set('end', end);

        const response = await fetch(url);
        if (!response.ok) {
            rangeLabel.textContent = 'Unable to load reports';
            return;
        }

        const data = await response.json();
        renderReport(data);
    };

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        updateQuickActive(null);
        loadReport();
    });

    quickButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const range = button.dataset.range;
            if (range === 'day') {
                setQuickRange(1, range);
            } else if (range === 'week') {
                setQuickRange(7, range);
            } else {
                setQuickRange(30, range);
            }
        });
    });

    // Default to last week
    setQuickRange(7, 'week');
})();
