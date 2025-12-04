// C'est Quoi Ce Niveau - Public Page Script

// ===========================================
// Configuration
// ===========================================

const TIER_CONFIG = {
    top_1k: { label: 'Top 1K', color: '#e63946', order: 1 },
    top_10k: { label: 'Top 10K', color: '#f4a261', order: 2 },
    top_50k: { label: 'Top 50K', color: '#e9c46a', order: 3 },
    ever_ranked: { label: 'Classé', color: '#9d4edd', order: 4 },
    final_league: { label: 'Ligue Ultime', color: '#7b2cbf', order: 5 },
    reached_12k: { label: '12K+', color: '#2a9d8f', order: 6 },
    trophy_10k_12k: { label: '10K-12K', color: '#219ebc', order: 7 },
    casual: { label: 'Casual (<10K)', color: '#57cc99', order: 8 },
    beginner: { label: 'Débutant (<8K)', color: '#6c757d', order: 9 }
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

const tagInput = document.getElementById('tournamentTag');
const searchBtn = document.getElementById('searchBtn');
const searchHint = document.getElementById('searchHint');
const resultsSection = document.getElementById('resultsSection');
const tournamentName = document.getElementById('tournamentName');
const tournamentStatus = document.getElementById('tournamentStatus');
const tournamentPlayers = document.getElementById('tournamentPlayers');
const analysisTime = document.getElementById('analysisTime');
const tierList = document.getElementById('tierList');
const panelFooter = document.getElementById('panelFooter');
const resetBtn = document.getElementById('resetBtn');
const tipText = document.getElementById('tipText');

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
    if (isSearching) return;
    
    const tag = tagInput.value.trim();
    if (!tag) {
        showHint('Entre le tag du tournoi', true);
        tagInput.focus();
        return;
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
    // Show tip panel again
    document.querySelector('.tip-footer').style.display = 'flex';
}

// ===========================================
// Results Display
// ===========================================

function displayResults(tournament, analysis) {
    // Tournament info
    tournamentName.textContent = tournament.name || 'Tournoi';
    
    // Status
    const statusText = formatStatus(tournament.status);
    tournamentStatus.textContent = statusText;
    tournamentStatus.className = 'tournament-status';
    if (tournament.status === 'ended') tournamentStatus.classList.add('ended');
    if (tournament.status === 'inProgress') tournamentStatus.classList.add('live');
    
    // Players count
    tournamentPlayers.textContent = `${tournament.membersList}/${tournament.maxCapacity} joueurs`;
    
    // Analysis time
    analysisTime.textContent = `${analysis.elapsed_seconds}s`;
    
    // Tier distribution
    displayTierDistribution(analysis.analysis);
    
    // Footer stats
    const stats = analysis.analysis.stats;
    panelFooter.innerHTML = `
        <span>Analysé : ${stats.successful}/${stats.total} joueurs</span>
        <span class="${stats.errors > 0 ? 'footer-errors' : ''}">${stats.errors > 0 ? stats.errors + ' erreurs' : 'Aucune erreur'}</span>
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
        html += `
            <div class="tier-row">
                <div class="tier-color" style="background: ${config.color};"></div>
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
    
    // Handle empty results
    if (sortedTiers.length === 0) {
        html = '<div class="tier-row"><div class="tier-label">Aucune donnée disponible</div></div>';
    }
    
    tierList.innerHTML = html;
}

function formatStatus(status) {
    const statusMap = {
        'inPreparation': 'En préparation',
        'inProgress': 'En cours',
        'ended': 'Terminé'
    };
    return statusMap[status] || status || 'Inconnu';
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

