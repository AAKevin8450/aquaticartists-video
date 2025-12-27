(() => {
    const startInput = document.getElementById('reportStart');
    const endInput = document.getElementById('reportEnd');
    const form = document.getElementById('reportFilters');
    const quickButtons = document.querySelectorAll('[data-range]');
    const rangeLabel = document.getElementById('reportRangeLabel');
    const expandedServices = new Set();  // Track which services are expanded

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

    const formatUsageAmount = (amount, usageType) => {
        if (!amount || amount === 0) return '0';

        const amt = Number(amount);
        const type = (usageType || '').toLowerCase();

        // Token formatting
        if (type.includes('token')) {
            if (amt >= 1000000) return `${(amt / 1000000).toFixed(2)}M tokens`;
            if (amt >= 1000) return `${(amt / 1000).toFixed(1)}K tokens`;
            return `${Math.round(amt)} tokens`;
        }

        // Request formatting
        if (type.includes('request')) {
            if (amt >= 1000) return `${(amt / 1000).toFixed(1)}K requests`;
            return `${Math.round(amt)} requests`;
        }

        // Storage formatting
        if (type.includes('gb')) {
            return `${amt.toFixed(2)} GB`;
        }

        // Byte formatting
        if (type.includes('byte')) {
            return formatBytes(amt);
        }

        // Generic fallback
        return formatNumber(amt);
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

    // ============================================================================
    // BILLING DATA FUNCTIONS
    // ============================================================================

    const loadBillingData = async (start, end, refresh = false) => {
        try {
            const url = new URL('/reports/api/billing/summary', window.location.origin);
            if (start) url.searchParams.set('start', start);
            if (end) url.searchParams.set('end', end);
            if (refresh) url.searchParams.set('refresh', 'true');

            const response = await fetch(url);

            if (!response.ok) {
                if (response.status === 503) {
                    showBillingError('AWS billing bucket not configured. Add BILLING_BUCKET_NAME to .env');
                    return;
                }
                throw new Error('Failed to load billing data');
            }

            const data = await response.json();
            renderBillingData(data);
            document.getElementById('billingSection').style.display = 'block';
            document.getElementById('billingError').style.display = 'none';
        } catch (error) {
            console.error('Billing error:', error);
            showBillingError(error.message);
        }
    };

    const renderBillingData = (data) => {
        // Format currency with 4 decimal places for billing
        const formatBillingCurrency = (value) => {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency: 'USD',
                minimumFractionDigits: 4,
                maximumFractionDigits: 4
            }).format(value || 0);
        };

        // Render service breakdown table with expandable rows
        const tbody = document.getElementById('billingServiceRows');
        tbody.innerHTML = '';

        if (!data.services || data.services.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 3;
            cell.className = 'text-center reports-muted';
            cell.textContent = 'No billing data available';
            row.appendChild(cell);
            tbody.appendChild(row);
        } else {
            data.services.forEach((service) => {
                // Main service row
                const row = document.createElement('tr');
                row.style.cursor = 'pointer';
                row.dataset.serviceCode = service.service_code;

                // Expand/collapse indicator
                const nameCell = document.createElement('td');
                const hasOperations = service.operations && service.operations.length > 0;
                if (hasOperations) {
                    const icon = document.createElement('i');
                    icon.className = 'bi bi-chevron-right me-2';
                    icon.style.transition = 'transform 0.2s';
                    icon.dataset.expandIcon = service.service_code;
                    nameCell.appendChild(icon);
                }
                nameCell.appendChild(document.createTextNode(service.service_name));
                nameCell.style.fontWeight = '600';

                const costCell = document.createElement('td');
                costCell.className = 'text-end';
                costCell.textContent = formatBillingCurrency(service.cost);

                const percentCell = document.createElement('td');
                percentCell.className = 'text-end';
                percentCell.textContent = `${service.percent.toFixed(1)}%`;

                row.appendChild(nameCell);
                row.appendChild(costCell);
                row.appendChild(percentCell);

                // Click handler for expand/collapse
                if (hasOperations) {
                    row.addEventListener('click', () => {
                        toggleServiceExpanded(service.service_code);
                    });
                }

                tbody.appendChild(row);

                // Operations detail rows (initially hidden)
                if (hasOperations) {
                    service.operations.forEach((op) => {
                        const opRow = document.createElement('tr');
                        opRow.className = 'billing-operation-row';
                        opRow.dataset.parentService = service.service_code;
                        opRow.style.display = 'none';
                        opRow.style.backgroundColor = '#f9fafb';

                        const opNameCell = document.createElement('td');
                        opNameCell.style.paddingLeft = '2rem';
                        opNameCell.innerHTML = `
                            <div style="font-size: 0.9rem;">${op.operation_name}</div>
                            <div style="font-size: 0.75rem; color: #6b7280;">
                                ${formatUsageAmount(op.usage_amount, op.usage_type)}
                            </div>
                        `;

                        const opCostCell = document.createElement('td');
                        opCostCell.className = 'text-end';
                        opCostCell.textContent = formatBillingCurrency(op.cost);

                        const opPercentCell = document.createElement('td');
                        opPercentCell.className = 'text-end';
                        opPercentCell.innerHTML = `<span style="font-size: 0.85rem; color: #6b7280;">${op.percent.toFixed(1)}%</span>`;

                        opRow.appendChild(opNameCell);
                        opRow.appendChild(opCostCell);
                        opRow.appendChild(opPercentCell);

                        tbody.appendChild(opRow);
                    });
                }
            });
        }

        // Update subtitle with total cost
        const subtitle = document.getElementById('billingSubtitle');
        subtitle.textContent = `${formatCurrency(data.total_cost)} total AWS costs`;

        // Render daily bars with date labels and cost amounts
        const costs = (data.daily || []).map(d => d.cost);
        const maxCost = Math.max(...costs, 0);
        const floor = maxCost === 0 ? 8 : 2;

        const container = document.getElementById('billingBarsContainer');
        container.innerHTML = '';
        container.style.display = 'flex';
        container.style.gap = '4px';
        container.style.alignItems = 'stretch';
        container.style.height = '250px';
        container.style.position = 'relative';
        container.style.backgroundImage = 'linear-gradient(to bottom, transparent 0%, transparent calc(100% - 1px), #e5e7eb calc(100% - 1px), #e5e7eb 100%)';
        container.style.backgroundSize = '100% 25%';

        data.daily.forEach((item) => {
            // Create wrapper for bar + labels
            const wrapper = document.createElement('div');
            wrapper.style.flex = '1';
            wrapper.style.display = 'flex';
            wrapper.style.flexDirection = 'column';
            wrapper.style.alignItems = 'center';
            wrapper.style.justifyContent = 'flex-end';
            wrapper.style.minWidth = '0';
            wrapper.style.position = 'relative';

            // Create bar container (to control bar height)
            const barContainer = document.createElement('div');
            barContainer.style.width = '100%';
            barContainer.style.display = 'flex';
            barContainer.style.flexDirection = 'column';
            barContainer.style.alignItems = 'center';
            barContainer.style.flex = '1';
            barContainer.style.justifyContent = 'flex-end';
            barContainer.style.position = 'relative';

            // Create cost label (above bar)
            const costLabel = document.createElement('span');
            costLabel.textContent = `$${item.cost.toFixed(2)}`;
            costLabel.style.fontSize = '9px';
            costLabel.style.color = '#374151';
            costLabel.style.fontWeight = '600';
            costLabel.style.marginBottom = '2px';
            costLabel.style.whiteSpace = 'nowrap';
            costLabel.style.userSelect = 'none';

            // Create bar
            const bar = document.createElement('span');
            bar.style.width = '100%';
            bar.style.backgroundColor = '#f97316';
            bar.style.borderRadius = '2px 2px 0 0';
            bar.style.transition = 'all 0.2s';
            bar.style.cursor = 'pointer';
            const height = maxCost ? Math.max(floor, Math.round((item.cost / maxCost) * 100)) : floor;
            bar.style.height = `${height}%`;
            bar.title = `${item.day}: ${formatCurrency(item.cost)}`;

            // Add hover effect
            bar.addEventListener('mouseenter', () => {
                bar.style.backgroundColor = '#ea580c';
            });
            bar.addEventListener('mouseleave', () => {
                bar.style.backgroundColor = '#f97316';
            });

            // Create date label (format: MM/DD)
            const dateLabel = document.createElement('span');
            const dateParts = item.day.split('-');
            dateLabel.textContent = `${dateParts[1]}/${dateParts[2]}`;
            dateLabel.style.fontSize = '10px';
            dateLabel.style.color = '#6b7280';
            dateLabel.style.marginTop = '4px';
            dateLabel.style.transform = 'rotate(-45deg)';
            dateLabel.style.transformOrigin = 'center';
            dateLabel.style.whiteSpace = 'nowrap';
            dateLabel.style.userSelect = 'none';
            dateLabel.style.height = '20px';
            dateLabel.style.display = 'flex';
            dateLabel.style.alignItems = 'center';
            dateLabel.style.justifyContent = 'center';

            barContainer.appendChild(costLabel);
            barContainer.appendChild(bar);
            wrapper.appendChild(barContainer);
            wrapper.appendChild(dateLabel);
            container.appendChild(wrapper);
        });
    };

    const showBillingError = (message) => {
        document.getElementById('billingSection').style.display = 'none';
        document.getElementById('billingError').style.display = 'block';
        document.getElementById('billingErrorMessage').textContent = message;
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

    const toggleServiceExpanded = (serviceCode) => {
        const isExpanded = expandedServices.has(serviceCode);
        const icon = document.querySelector(`[data-expand-icon="${serviceCode}"]`);
        const operationRows = document.querySelectorAll(`[data-parent-service="${serviceCode}"]`);

        if (isExpanded) {
            // Collapse
            expandedServices.delete(serviceCode);
            if (icon) {
                icon.style.transform = 'rotate(0deg)';
            }
            operationRows.forEach(row => {
                row.style.display = 'none';
            });
        } else {
            // Expand
            expandedServices.add(serviceCode);
            if (icon) {
                icon.style.transform = 'rotate(90deg)';
            }
            operationRows.forEach(row => {
                row.style.display = 'table-row';
            });
        }
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

        // Load billing data after main report
        loadBillingData(start, end);
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

    // Add refresh button handler
    const refreshBillingBtn = document.getElementById('refreshBillingBtn');
    if (refreshBillingBtn) {
        refreshBillingBtn.addEventListener('click', async () => {
            await loadBillingData(startInput.value, endInput.value, true);
        });
    }

    // Zero-cost filter toggle
    const hideZeroCostToggle = document.getElementById('hideZeroCostToggle');
    if (hideZeroCostToggle) {
        hideZeroCostToggle.addEventListener('change', (e) => {
            const hide = e.target.checked;
            const tbody = document.getElementById('billingServiceRows');
            const rows = tbody.querySelectorAll('tr');

            rows.forEach((row) => {
                // Skip operation detail rows (let parent control them)
                if (row.classList.contains('billing-operation-row')) {
                    return;
                }

                // Check if this service row has zero cost
                const costCell = row.querySelector('td:nth-child(2)');
                if (costCell) {
                    const costText = costCell.textContent;
                    const cost = parseFloat(costText.replace(/[$,]/g, ''));

                    if (hide && cost === 0) {
                        row.style.display = 'none';
                        // Also hide its operation rows
                        const serviceCode = row.dataset.serviceCode;
                        if (serviceCode) {
                            const opRows = tbody.querySelectorAll(`[data-parent-service="${serviceCode}"]`);
                            opRows.forEach(opRow => opRow.style.display = 'none');
                        }
                    } else {
                        row.style.display = 'table-row';
                        // Restore operation rows if parent was expanded
                        const serviceCode = row.dataset.serviceCode;
                        if (serviceCode && expandedServices.has(serviceCode)) {
                            const opRows = tbody.querySelectorAll(`[data-parent-service="${serviceCode}"]`);
                            opRows.forEach(opRow => opRow.style.display = 'table-row');
                        }
                    }
                }
            });
        });
    }

    // Default to last week
    setQuickRange(7, 'week');
})();
