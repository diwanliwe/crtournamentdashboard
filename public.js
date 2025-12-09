// C'est Quoi Ce Niveau - Public Page Script

// ===========================================
// Configuration
// ===========================================

const TIER_CONFIG = {
    top_1k: { label: 'Top 1K', color: '#e63946', order: 1 },
    top_10k: { label: 'Top 10K', color: '#f4a261', order: 2 },
    top_50k: { label: 'Top 50K', color: '#e9c46a', order: 3 },
    ever_ranked: { label: 'Classé', color: '#9d4edd', order: 4 },
    final_league: { label: 'Champion Suprême', color: '#7b2cbf', order: 5 },
    reached_12k: { label: '12K+', color: '#2a9d8f', order: 6 },
    trophy_10k_12k: { label: '10K-12K', color: '#219ebc', order: 7 },
    casual: { label: 'Casual', sub: '8K-10K', color: '#57cc99', order: 8 },
    beginner: { label: 'Débutant', sub: '<8K', color: '#6c757d', order: 9 }
};

const TIPS = [
    "Les joueurs Top 1K sont parmi les meilleurs au monde !",
    "Un joueur classé a atteint le classement mondial au moins une fois.",
    "La Ligue Ultime est le dernier palier avant d'être classé.",
    "Les joueurs Casual ont entre 8000 et 10000 trophées de base.",
    "L'analyse peut prendre jusqu'à 30 secondes pour les gros tournois.",
    "Le tag du tournoi se trouve dans les détails du tournoi en jeu.",
    "Tu peux copier le tag directement depuis Clash Royale !",
    "Les pourcentages montrent la répartition des niveaux de joueurs.",
    "Un tournoi équilibré a une bonne distribution de tous les niveaux.",
    "Les Top 10K représentent l'élite des joueurs réguliers.",
];

const TIP_ROTATION_INTERVAL = 6000; // 6 seconds

// ===========================================
// DOM Elements
// ===========================================

const appContainer = document.querySelector('.app');
const tagInput = document.getElementById('tournamentTag');
const searchBtn = document.getElementById('searchBtn');
const searchHint = document.getElementById('searchHint');
const resultsSection = document.getElementById('resultsSection');
const headerTag = document.getElementById('headerTag');
const headerTitle = document.getElementById('headerTitle');
const headerSubtitle = document.getElementById('headerSubtitle');
const headerProgress = document.getElementById('headerProgress');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const playerBarText = document.getElementById('playerBarText');
const analysisTime = document.getElementById('analysisTime');
const tierList = document.getElementById('tierList');
const panelFooter = document.getElementById('panelFooter');
const resetBtn = document.getElementById('resetBtn');
const tipText = document.getElementById('tipText');
const infoBtn = document.getElementById('infoBtn');
const infoModal = document.getElementById('infoModal');
const modalClose = document.getElementById('modalClose');

// Default header content (to restore on reset)
const DEFAULT_TITLE = "C'est quoi ce niveau ?";
const DEFAULT_SUBTITLE = "Analyse ton tournoi";

// Progress bar update interval
let progressInterval = null;

// ===========================================
// State
// ===========================================

let isSearching = false;
let currentTipIndex = 0;
let tipInterval = null;

// ===========================================
// Initialization
// ===========================================

document.addEventListener('DOMContentLoaded', () => {
    // Event listeners
    searchBtn.addEventListener('click', handleSearch);
    tagInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSearch();
    });
    resetBtn.addEventListener('click', resetSearch);
    
    // Info modal event listeners
    infoBtn.addEventListener('click', openInfoModal);
    modalClose.addEventListener('click', closeInfoModal);
    infoModal.addEventListener('click', (e) => {
        // Close when clicking overlay (not modal content)
        if (e.target === infoModal) closeInfoModal();
    });
    
    // Start tip rotation
    showRandomTip();
    tipInterval = setInterval(rotateTip, TIP_ROTATION_INTERVAL);
    
    // Focus input on load
    tagInput.focus();
});

// ===========================================
// Search Flow
// ===========================================

async function handleSearch() {
    console.log('[Debug] handleSearch called');
    console.log('[Debug] posthog exists:', typeof posthog !== 'undefined');
    
    if (isSearching) return;
    
    const tag = tagInput.value.trim();
    if (!tag) {
        showHint('Entre le tag du tournoi', true);
        tagInput.focus();
        return;
    }
    
    // Track button click
    if (typeof posthog !== 'undefined') {
        posthog.capture('search_button_clicked');
        console.log('[PostHog] Event captured: search_button_clicked');
    } else {
        console.warn('[PostHog] posthog is not defined');
    }
    
    isSearching = true;
    setSearchingState(true);
    hideResults();
    
    try {
        // Step 1: Find tournament
        showHint('Recherche du tournoi...', false, true);
        const cleanTag = tag.replace(/^#/, '');
        
        const tournamentResponse = await fetch(`/api/tournament/${cleanTag}`);
        const tournamentData = await tournamentResponse.json();
        
        if (!tournamentResponse.ok) {
            throw new Error(tournamentData.detail || 'Tournoi non trouvé');
        }
        
        // Step 2: Analyze players
        showHint(`Tournoi trouvé ! Analyse de ${tournamentData.membersList} joueurs...`, false, true);
        
        const analyzeResponse = await fetch(`/api/tournament/${cleanTag}/analyze`);
        const analyzeData = await analyzeResponse.json();
        
        if (!analyzeResponse.ok) {
            throw new Error(analyzeData.detail || 'Erreur lors de l\'analyse');
        }
        
        // Step 3: Display results
        showHint('');
        displayResults(tournamentData, analyzeData);
        
    } catch (error) {
        console.error('Search error:', error);
        showHint(error.message || 'Une erreur est survenue', true);
    } finally {
        isSearching = false;
        setSearchingState(false);
    }
}

function setSearchingState(searching) {
    tagInput.disabled = searching;
    searchBtn.disabled = searching;
}

function showHint(message, isError = false, isLoading = false) {
    searchHint.textContent = message;
    searchHint.className = 'search-hint';
    if (isError) searchHint.classList.add('error');
    if (isLoading) searchHint.classList.add('loading');
}

function hideResults() {
    resultsSection.style.display = 'none';
}

function resetSearch() {
    hideResults();
    tagInput.value = '';
    tagInput.focus();
    showHint('');
    
    // Restore header to default
    headerTag.style.display = 'none';
    headerTitle.textContent = DEFAULT_TITLE;
    headerTitle.classList.remove('tournament-name');
    headerSubtitle.textContent = DEFAULT_SUBTITLE;
    headerSubtitle.style.display = 'block';
    headerProgress.classList.remove('active');
    
    // Clear progress interval if running
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    // Remove results-mode class to show search bar
    appContainer.classList.remove('results-mode');
    
    // Show tip panel again
    document.querySelector('.tip-footer').style.display = 'flex';
}

// ===========================================
// Results Display
// ===========================================

function displayResults(tournament, analysis) {
    // Update header with tournament info (like in-game)
    const cleanTag = tagInput.value.trim().replace(/^#/, '');
    headerTag.textContent = `#${cleanTag.toUpperCase()}`;
    headerTag.style.display = 'block';
    
    // Tournament name in the blue box (with smaller font class)
    headerTitle.textContent = tournament.name || 'Tournoi';
    headerTitle.classList.add('tournament-name');
    
    // Handle status display based on tournament state
    if (tournament.status === 'inProgress' && tournament.startedTime && tournament.duration) {
        // Show progress bar for ongoing tournaments
        headerSubtitle.style.display = 'none';
        headerProgress.classList.add('active');
        startProgressBar(tournament);
    } else {
        // Show status text for ended/preparation
        headerSubtitle.style.display = 'block';
        headerProgress.classList.remove('active');
        headerSubtitle.textContent = formatStatus(tournament.status);
        if (progressInterval) {
            clearInterval(progressInterval);
            progressInterval = null;
        }
    }
    
    // Player count bar
    playerBarText.textContent = `Joueurs : ${tournament.membersList}/${tournament.maxCapacity}`;
    
    // Add results-mode class to hide search bar
    appContainer.classList.add('results-mode');
    
    // Analysis time
    analysisTime.textContent = `${analysis.elapsed_seconds}s`;
    
    // Tier distribution
    displayTierDistribution(analysis.analysis);
    
    // Log cache stats to console
    const stats = analysis.analysis.stats;
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    console.log(`📊 Analysis: ${tournament.name}`);
    console.log(`⏱️  Time: ${analysis.elapsed_seconds}s`);
    console.log(`👥 Players: ${stats.successful}/${stats.total}`);
    
    if (stats.cache_enabled) {
        console.log(`💾 FROM CACHE: ${stats.from_cache} players`);
        console.log(`🌐 FROM API: ${stats.from_api} players`);
        const cachePercent = stats.successful > 0 ? Math.round(stats.from_cache / stats.successful * 100) : 0;
        console.log(`📈 Cache hit rate: ${cachePercent}%`);
        
        // Show cache timing info
        if (stats.cache_info && stats.cache_info.oldest_cached_at) {
            const cachedAt = new Date(stats.cache_info.oldest_cached_at);
            const expiresAt = new Date(stats.cache_info.expires_at);
            const now = new Date();
            const minutesRemaining = Math.round((expiresAt - now) / 1000 / 60);
            
            console.log(`🕐 Oldest cache: ${cachedAt.toLocaleTimeString()}`);
            if (minutesRemaining > 0) {
                const hoursRemaining = Math.floor(minutesRemaining / 60);
                const mins = minutesRemaining % 60;
                console.log(`⏳ Expires in: ${hoursRemaining}h ${mins}m`);
            } else {
                console.log(`⏳ Cache expired (will refresh on next fetch)`);
            }
        }
        
        if (stats.from_cache > 0 && stats.from_api === 0) {
            console.log(`✅ 100% from cache - No API calls needed!`);
        } else if (stats.from_cache > 0) {
            console.log(`✅ Saved ${stats.from_cache} API calls thanks to cache`);
        }
    } else {
        console.log(`⚠️ KV Cache not enabled`);
    }
    console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    
    // Footer stats (simple - no cache info for social sharing)
    const errorsText = stats.errors > 0 ? ` (${stats.errors} erreurs)` : '';
    
    panelFooter.innerHTML = `
        <span>Analysé : ${stats.successful}/${stats.total} joueurs${errorsText}</span>
    `;
    
    // Hide tip panel when showing results
    document.querySelector('.tip-footer').style.display = 'none';
    
    // Show results
    resultsSection.style.display = 'block';
    
    // Scroll to results on mobile
    setTimeout(() => {
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
}

function displayTierDistribution(analysis) {
    const summary = analysis.summary;
    
    // Sort tiers by order (best first)
    const sortedTiers = Object.entries(summary)
        .filter(([tier, data]) => data.count > 0)
        .sort((a, b) => {
            const orderA = TIER_CONFIG[a[0]]?.order || 99;
            const orderB = TIER_CONFIG[b[0]]?.order || 99;
            return orderA - orderB;
        });
    
    // Build tier rows
    let html = '';
    for (const [tier, tierData] of sortedTiers) {
        const config = TIER_CONFIG[tier] || { label: tier, color: '#666' };
        const subLabel = config.sub ? `<span class="tier-label-sub">${config.sub}</span>` : '';
        html += `
            <div class="tier-row">
                <div class="tier-color" style="background: ${config.color};"></div>
                <div class="tier-label">${config.label}${subLabel}</div>
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
    
    // Handle empty results
    if (sortedTiers.length === 0) {
        html = '<div class="tier-row"><div class="tier-label">Aucune donnée disponible</div></div>';
    }
    
    tierList.innerHTML = html;
}

function formatStatus(status) {
    // Match in-game language
    const statusMap = {
        'inPreparation': 'Tournoi en préparation',
        'inProgress': 'En cours', // Will be replaced by progress bar
        'ended': 'Tournoi terminé'
    };
    return statusMap[status] || status || 'Inconnu';
}

// ===========================================
// Progress Bar for Ongoing Tournaments
// ===========================================

function startProgressBar(tournament) {
    // Parse Clash Royale API date format (e.g., "20251120T172936.000Z")
    const parseApiDate = (dateStr) => {
        if (!dateStr) return null;
        // Convert "20251120T172936.000Z" to "2025-11-20T17:29:36.000Z"
        const formatted = dateStr.replace(
            /(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/,
            '$1-$2-$3T$4:$5:$6'
        );
        return new Date(formatted);
    };
    
    const startTime = parseApiDate(tournament.startedTime);
    const durationMs = tournament.duration * 1000; // Convert to milliseconds
    const endTime = new Date(startTime.getTime() + durationMs);
    
    const updateProgress = () => {
        const now = new Date();
        const elapsed = now - startTime;
        const remaining = endTime - now;
        
        if (remaining <= 0) {
            // Tournament has ended
            progressFill.style.width = '100%';
            progressText.textContent = 'Tournoi terminé';
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            return;
        }
        
        // Calculate progress percentage
        const progress = Math.min((elapsed / durationMs) * 100, 100);
        progressFill.style.width = `${progress}%`;
        
        // Format remaining time
        const remainingSeconds = Math.floor(remaining / 1000);
        const hours = Math.floor(remainingSeconds / 3600);
        const minutes = Math.floor((remainingSeconds % 3600) / 60);
        const seconds = remainingSeconds % 60;
        
        if (hours > 0) {
            progressText.textContent = `Fin dans : ${hours}h ${minutes}min`;
        } else if (minutes > 0) {
            progressText.textContent = `Fin dans : ${minutes}min ${seconds}s`;
        } else {
            progressText.textContent = `Fin dans : ${seconds}s`;
        }
    };
    
    // Update immediately and then every second
    updateProgress();
    progressInterval = setInterval(updateProgress, 1000);
}

// ===========================================
// Tips Rotation
// ===========================================

function showRandomTip() {
    currentTipIndex = Math.floor(Math.random() * TIPS.length);
    tipText.textContent = TIPS[currentTipIndex];
}

function rotateTip() {
    // Fade out
    tipText.classList.add('fade');
    
    setTimeout(() => {
        // Change tip
        currentTipIndex = (currentTipIndex + 1) % TIPS.length;
        tipText.textContent = TIPS[currentTipIndex];
        
        // Fade in
        tipText.classList.remove('fade');
    }, 300);
}

// ===========================================
// Info Modal
// ===========================================

function openInfoModal() {
    infoModal.classList.add('active');
    document.body.style.overflow = 'hidden'; // Prevent background scroll
    
    // Track with PostHog
    if (typeof posthog !== 'undefined') {
        posthog.capture('info_button_clicked');
        console.log('[PostHog] Event captured: info_button_clicked');
    }
}

function closeInfoModal() {
    infoModal.classList.remove('active');
    document.body.style.overflow = ''; // Restore scroll
}

// Close modal with Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && infoModal.classList.contains('active')) {
        closeInfoModal();
    }
});

