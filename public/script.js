// Tournament Dashboard Script
const REFRESH_INTERVAL = 5000; // 5 seconds (increased to prevent request pile-up)
let pollingInterval = null;
let isMonitoring = false;
let fetchInProgress = false; // Prevent duplicate requests

// Tier display configuration - ordered by difficulty (hardest first)
const TIER_CONFIG = {
    top_1k: { label: 'Top 1K', color: '#ff6b6b', order: 1 },
    top_10k: { label: 'Top 10K', color: '#feca57', order: 2 },
    top_50k: { label: 'Top 50K', color: '#ff9ff3', order: 3 },
    ever_ranked: { label: 'Ranked', color: '#a55eea', order: 4 },
    final_league: { label: 'Supreme Champion', color: '#5f27cd', order: 5 },
    reached_15k: { label: 'Reached 15K', color: '#00d2d3', order: 6 },
    seasonal_10k_15k: { label: '10K-15K', color: '#54a0ff', order: 7 },
    casual: { label: 'Casual (<10K)', color: '#1dd1a1', order: 8 },
    beginner: { label: 'Beginner (<8K)', color: '#576574', order: 9 }
};

// DOM Elements
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const statusIndicator = document.getElementById('statusIndicator');
const lastUpdateEl = document.getElementById('lastUpdate');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    startBtn.addEventListener('click', startMonitoring);
    stopBtn.addEventListener('click', stopMonitoring);

    // Allow Enter key to start monitoring from any input
    document.querySelectorAll('.tag-input').forEach(input => {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !isMonitoring) {
                startMonitoring();
            }
        });
    });

    // Analyze button click handlers
    document.querySelectorAll('.btn-analyze').forEach(btn => {
        btn.addEventListener('click', () => {
            const index = btn.getAttribute('data-index');
            const tag = document.getElementById(`tag-${index}`).value.trim();
            if (tag) {
                // Track button click
                if (typeof posthog !== 'undefined') {
                    posthog.capture('analyze_button_clicked');
                    console.log('[PostHog] Event captured: analyze_button_clicked');
                } else {
                    console.warn('[PostHog] posthog is not defined');
                }
                analyzeTourn(tag, index);
            }
        });
    });
});

function startMonitoring() {
    const tags = getTournamentTags();
    
    if (tags.every(tag => !tag)) {
        alert('Please enter at least one tournament tag');
        return;
    }

    isMonitoring = true;
    startBtn.disabled = true;
    stopBtn.disabled = false;
    statusIndicator.classList.add('active');
    statusIndicator.querySelector('.text').textContent = 'Live';

    // Disable inputs while monitoring
    document.querySelectorAll('.tag-input').forEach(input => {
        input.disabled = true;
    });

    // Fetch immediately, then start interval
    fetchAllTournaments();
    pollingInterval = setInterval(fetchAllTournaments, REFRESH_INTERVAL);
}

function stopMonitoring() {
    isMonitoring = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;
    statusIndicator.classList.remove('active');
    statusIndicator.querySelector('.text').textContent = 'Idle';

    // Re-enable inputs
    document.querySelectorAll('.tag-input').forEach(input => {
        input.disabled = false;
    });

    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function getTournamentTags() {
    return [
        document.getElementById('tag-0').value.trim(),
        document.getElementById('tag-1').value.trim(),
        document.getElementById('tag-2').value.trim()
    ];
}

async function fetchAllTournaments() {
    // Prevent duplicate requests if previous fetch is still in progress
    if (fetchInProgress) {
        console.log('Skipping fetch - previous request still in progress');
        return;
    }
    
    fetchInProgress = true;
    const tags = getTournamentTags();
    
    try {
        const promises = tags.map((tag, index) => {
            if (tag) {
                return fetchTournament(tag, index);
            } else {
                return Promise.resolve(null);
            }
        });

        await Promise.all(promises);
        updateLastUpdateTime();
    } finally {
        fetchInProgress = false;
    }
}

async function fetchTournament(tag, cardIndex) {
    const card = document.querySelector(`.tournament-card[data-index="${cardIndex}"]`);
    card.classList.add('loading');

    try {
        // Remove # if present for the API call, the backend will handle it
        const cleanTag = tag.replace(/^#/, '');
        // Add timestamp to prevent caching
        const response = await fetch(`/api/tournament/${cleanTag}?t=${Date.now()}`);
        const data = await response.json();

        if (response.ok) {
            console.log(`[Q${cardIndex + 1}] ${data.name}: ${data.membersList}/${data.maxCapacity} players`);
            updateCard(cardIndex, data);
        } else {
            updateCardError(cardIndex, data.detail || data.error || 'Unknown error');
        }
    } catch (error) {
        console.error(`Error fetching tournament ${tag}:`, error);
        updateCardError(cardIndex, 'Network error');
    } finally {
        card.classList.remove('loading');
    }
}

function updateCard(index, data) {
    const card = document.querySelector(`.tournament-card[data-index="${index}"]`);
    
    // Update status badge
    const statusBadge = card.querySelector('.status-badge');
    statusBadge.textContent = formatStatus(data.status);
    statusBadge.setAttribute('data-status', data.status);

    // Update tournament name
    const nameEl = card.querySelector('.tournament-name');
    nameEl.textContent = data.name || 'Unknown Tournament';
    nameEl.classList.add('loaded');

    // Update player count
    const currentCount = card.querySelector('.count-current');
    const maxCount = card.querySelector('.count-max');
    currentCount.textContent = data.membersList || data.capacity || 0;
    maxCount.textContent = data.maxCapacity || 1000;

    // Update progress bar
    const progressFill = card.querySelector('.progress-fill');
    const percentage = ((data.membersList || data.capacity || 0) / (data.maxCapacity || 1000)) * 100;
    progressFill.style.width = `${percentage}%`;

    // Enable analyze button
    const analyzeBtn = card.querySelector('.btn-analyze');
    analyzeBtn.disabled = false;
}

function updateCardError(index, errorMessage) {
    const card = document.querySelector(`.tournament-card[data-index="${index}"]`);
    
    // Update status badge
    const statusBadge = card.querySelector('.status-badge');
    statusBadge.textContent = 'Error';
    statusBadge.setAttribute('data-status', 'error');

    // Update tournament name
    const nameEl = card.querySelector('.tournament-name');
    nameEl.textContent = errorMessage;
    nameEl.classList.remove('loaded');

    // Reset counts
    const currentCount = card.querySelector('.count-current');
    const maxCount = card.querySelector('.count-max');
    currentCount.textContent = '--';
    maxCount.textContent = '--';

    // Reset progress bar
    const progressFill = card.querySelector('.progress-fill');
    progressFill.style.width = '0%';

    // Disable analyze button
    const analyzeBtn = card.querySelector('.btn-analyze');
    analyzeBtn.disabled = true;
}

function formatStatus(status) {
    const statusMap = {
        'inPreparation': 'Prep',
        'inProgress': 'Live',
        'ended': 'Ended'
    };
    return statusMap[status] || status || '--';
}

function updateLastUpdateTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('en-US', { 
        hour12: false, 
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit' 
    });
    lastUpdateEl.textContent = timeString;
}

// Analysis functions
async function analyzeTourn(tag, cardIndex) {
    const card = document.querySelector(`.tournament-card[data-index="${cardIndex}"]`);
    const analyzeBtn = card.querySelector('.btn-analyze');
    const analysisResults = card.querySelector('.analysis-results');
    const tierBarsContainer = analysisResults.querySelector('.tier-bars');
    
    // Update button state
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing...';
    analyzeBtn.classList.add('analyzing');
    
    // Show loading state in results area
    analysisResults.style.display = 'block';
    tierBarsContainer.innerHTML = '<div class="analysis-loading">Analyzing players... This may take a while for large tournaments.</div>';
    analysisResults.querySelector('.analysis-time').textContent = '';

    const cleanTag = tag.replace(/^#/, '');

    try {
        const response = await fetch(`/api/tournament/${cleanTag}/analyze`);
        const data = await response.json();

        if (response.ok) {
            displayAnalysis(cardIndex, data);
        } else {
            displayAnalysisError(cardIndex, data.detail || data.error || 'Analysis failed');
        }
    } catch (error) {
        console.error(`Error analyzing tournament ${tag}:`, error);
        displayAnalysisError(cardIndex, 'Network error during analysis');
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze Players';
        analyzeBtn.classList.remove('analyzing');
    }
}

function displayAnalysis(cardIndex, data) {
    const card = document.querySelector(`.tournament-card[data-index="${cardIndex}"]`);
    const analysisResults = card.querySelector('.analysis-results');
    const tierBarsContainer = analysisResults.querySelector('.tier-bars');
    const timeEl = analysisResults.querySelector('.analysis-time');
    
    // Update time
    timeEl.textContent = `${data.elapsed_seconds}s`;
    
    // Get summary and sort by difficulty (order) - hardest first
    const summary = data.analysis.summary;
    const sortedTiers = Object.entries(summary)
        .filter(([tier, data]) => data.count > 0)
        .sort((a, b) => {
            const orderA = TIER_CONFIG[a[0]]?.order || 99;
            const orderB = TIER_CONFIG[b[0]]?.order || 99;
            return orderA - orderB;
        });
    
    // Build tier bars HTML
    let html = '';
    for (const [tier, tierData] of sortedTiers) {
        const config = TIER_CONFIG[tier] || { label: tier, color: '#666' };
        html += `
            <div class="tier-row">
                <div class="tier-label">${config.label}</div>
                <div class="tier-bar-container">
                    <div class="tier-bar" style="width: ${tierData.percent}%; background: ${config.color};"></div>
                </div>
                <div class="tier-stats">
                    <span class="tier-count">${tierData.count}</span>
                    <span class="tier-percent">${tierData.percent}%</span>
                </div>
            </div>
        `;
    }
    
    // Add stats footer
    const stats = data.analysis.stats;
    const errorsText = stats.errors > 0 ? `${stats.errors} errors` : 'no errors';
    html += `
        <div class="analysis-footer">
            <span>${stats.successful}/${stats.total} players</span>
            <span class="${stats.errors > 0 ? 'error-info' : 'fetch-info'}">${errorsText}</span>
        </div>
    `;
    
    tierBarsContainer.innerHTML = html;
    analysisResults.style.display = 'block';
}

function displayAnalysisError(cardIndex, errorMessage) {
    const card = document.querySelector(`.tournament-card[data-index="${cardIndex}"]`);
    const analysisResults = card.querySelector('.analysis-results');
    const tierBarsContainer = analysisResults.querySelector('.tier-bars');
    
    tierBarsContainer.innerHTML = `<div class="analysis-error">${errorMessage}</div>`;
    analysisResults.style.display = 'block';
}

