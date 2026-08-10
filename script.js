document.addEventListener("DOMContentLoaded", function () {

    /* =================================
            API CONFIGURATION
    ================================= */
    // Replace with your actual Vercel deployment URL
const API_URL = "https://aqms-dashboard-orpin.vercel.app/api/live-data";
    /* =================================
            CALIBRATION CONSTANTS
    ================================= */
    const MQ2_MIN = 200;    // ppm - clean-air baseline
    const MQ2_MAX = 1000;   // ppm - hazardous ceiling

    const MQ135_MIN = 100;  // ppm - clean-air baseline
    const MQ135_MAX = 1000; // ppm - hazardous ceiling

    const MAX_CHART_POINTS = 10; // Keep the last 10 readings on live charts

    /* =================================
            CHART INITIALIZATION
    ================================= */
    // Smoke Chart (MQ-2)
    const smokeCanvas = document.getElementById("smokeChart");
    const smokeChart = new Chart(smokeCanvas, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                label: "MQ-2 Smoke Level",
                data: [],
                borderColor: "#355CFF",
                backgroundColor: "rgba(53, 92, 255, 0.10)",
                borderWidth: 3,
                pointRadius: 3,
                pointHoverRadius: 6,
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: false } }
        }
    });

    // Environment Chart (Temp & Humidity)
    const environmentCanvas = document.getElementById("environmentChart");
    const environmentChart = new Chart(environmentCanvas, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Temperature (°C)",
                    data: [],
                    borderColor: "#E45757",
                    borderWidth: 3,
                    tension: 0.4,
                    pointRadius: 3,
                    yAxisID: "temperatureAxis"
                },
                {
                    label: "Humidity (%)",
                    data: [],
                    borderColor: "#3B73D1",
                    borderWidth: 3,
                    tension: 0.4,
                    pointRadius: 3,
                    yAxisID: "humidityAxis"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true, position: "bottom" } },
            scales: {
                temperatureAxis: { type: "linear", position: "left", beginAtZero: false },
                humidityAxis: { type: "linear", position: "right", beginAtZero: false, grid: { drawOnChartArea: false } }
            }
        }
    });

    /* =================================
            CALCULATION HELPERS
    ================================= */
    function normalize(value, min, max) {
        return Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
    }

    function classifyScore(value) {
        if (value >= 80) {
            return { label: "GOOD", className: "good", message: "Environment is Safe" };
        } else if (value >= 50) {
            return { label: "MODERATE", className: "moderate", message: "Environment is Acceptable" };
        } else {
            return { label: "POOR", className: "poor", message: "Environment is Unsafe" };
        }
    }

    function applyBadge(elementId, normalizedPollutionValue) {
        const element = document.getElementById(elementId);
        if (!element) return;

        const sensorScore = Math.round(100 - normalizedPollutionValue);
        const classification = classifyScore(sensorScore);

        element.textContent = classification.label;
        element.className = `status-badge ${classification.className}`;
    }

    /* =================================
            UI UPDATE FUNCTION
    ================================= */
    function updateDashboardUI(data) {
        // 1. Update Raw Sensor Displays
        document.getElementById("mq2Value").textContent = data.mq2;
        document.getElementById("mq135Value").textContent = data.mq135;
        document.getElementById("temperatureValue").textContent = data.temperature;
        document.getElementById("humidityValue").textContent = data.humidity;

        // 2. Normalization & Score Calculation
        const mq2Norm = normalize(data.mq2, MQ2_MIN, MQ2_MAX);
        const mq135Norm = normalize(data.mq135, MQ135_MIN, MQ135_MAX);

        // Prefer backend score if sent, otherwise calculate dynamically
        const score = data.score !== undefined ? data.score : Math.round(100 - ((0.4 * mq2Norm) + (0.6 * mq135Norm)));
        const overallClassification = classifyScore(score);

        // 3. Update Air Quality Score & Text Badges
        document.getElementById("aqScore").textContent = score;

        const qualityStatus = document.getElementById("qualityStatus");
        const qualityMessage = document.getElementById("qualityMessage");

        if (qualityStatus) {
            qualityStatus.textContent = overallClassification.label;
            qualityStatus.className = "";
            qualityStatus.classList.add(overallClassification.className);
        }

        if (qualityMessage) {
            qualityMessage.textContent = overallClassification.message;
        }

        // 4. Update Conic Score Ring
        const scoreRing = document.querySelector(".score-ring");
        if (scoreRing) {
            const sweepDegrees = (score / 100) * 360;
            scoreRing.style.background = `conic-gradient(var(--primary) 0deg ${sweepDegrees}deg, #E9ECF5 ${sweepDegrees}deg 360deg)`;
        }

        // 5. Update Per-Sensor Badges
        applyBadge("mq2Status", mq2Norm);
        applyBadge("mq135Status", mq135Norm);

        // 6. Update Last Reading Timestamp
        const now = new Date();
        const dateStr = now.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
        const timeStr = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        
        const lastUpdatedElem = document.getElementById("lastUpdated");
        if (lastUpdatedElem) {
            lastUpdatedElem.textContent = `${dateStr} | ${timeStr}`;
        }

        // 7. Dynamic Chart Real-Time Updates
        const labelTime = data.time ? data.time.substring(0, 5) : timeStr.substring(0, 5);

        // Smoke Chart Update
        smokeChart.data.labels.push(labelTime);
        smokeChart.data.datasets[0].data.push(data.mq2);
        if (smokeChart.data.labels.length > MAX_CHART_POINTS) {
            smokeChart.data.labels.shift();
            smokeChart.data.datasets[0].data.shift();
        }
        smokeChart.update();

        // Environment Chart Update
        environmentChart.data.labels.push(labelTime);
        environmentChart.data.datasets[0].data.push(data.temperature);
        environmentChart.data.datasets[1].data.push(data.humidity);
        if (environmentChart.data.labels.length > MAX_CHART_POINTS) {
            environmentChart.data.labels.shift();
            environmentChart.data.datasets[0].data.shift();
            environmentChart.data.datasets[1].data.shift();
        }
        environmentChart.update();
    }

    /* =================================
            FETCH DATA FROM VERCEL
    ================================= */
    async function fetchLiveData() {
        try {
            const response = await fetch(API_URL);
            if (!response.ok) throw new Error("Failed to fetch live data from server");

            const data = await response.json();
            updateDashboardUI(data);

        } catch (error) {
            console.error("Error fetching live dashboard metrics:", error);
        }
    }

    // Initial load and continuous 5-second polling interval
    fetchLiveData();
    setInterval(fetchLiveData, 5000);
});