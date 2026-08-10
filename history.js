/* =================================================
                API CONFIGURATION
================================================= */
// Replace with your live Vercel domain URL
const API_URL = "https://aqms-dashboard-orpin.vercel.app/api/live-data?mode=history";
// Storage for fetched Google Sheet records
let historyData = [];

/* =================================================
                ELEMENTS
================================================= */
const tableBody = document.getElementById("historyTableBody");
const searchInput = document.getElementById("searchInput");
const dateRange = document.getElementById("dateRange");
const statusFilter = document.getElementById("statusFilter");
const selectedRangeText = document.getElementById("selectedRangeText");
const exportButton = document.getElementById("exportButton");

/* =================================================
                FETCH LIVE DATA FROM VERCEL
================================================= */
async function fetchHistoryData() {
    tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center;">Loading historical logs...</td></tr>`;

    try {
        const response = await fetch(API_URL);
        if (!response.ok) throw new Error("Failed to connect to Vercel API");

        const data = await response.json();
        
        // Store returned records array
        historyData = data;

        // Apply active filters and populate the table
        filterData();

    } catch (error) {
        console.error("Error fetching history:", error);
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: red;">Failed to load history data. Please try again.</td></tr>`;
    }
}

/* =================================================
                DATE HELPERS
================================================= */
function getToday() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return today;
}

function convertToDate(dateString) {
    // Handles DD/MM/YYYY (Google Sheet format) and YYYY-MM-DD
    if (dateString.includes("/")) {
        const parts = dateString.split("/");
        return new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
    } else if (dateString.includes("-")) {
        const parts = dateString.split("-");
        return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    }
    return new Date();
}

/* =================================================
                DATE RANGE FILTER
================================================= */
function filterByDateRange(data) {
    const today = getToday();
    const selectedRange = dateRange.value;

    return data.filter(reading => {
        const readingDate = convertToDate(reading.date);
        const difference = Math.floor((today - readingDate) / (1000 * 60 * 60 * 24));

        if (selectedRange === "today") return difference === 0;
        if (selectedRange === "yesterday") return difference === 1;
        if (selectedRange === "last7days") return difference >= 0 && difference <= 7;
        if (selectedRange === "last30days") return difference >= 0 && difference <= 30;
        if (selectedRange === "lastyear") return difference >= 0 && difference <= 365;
        
        return true;
    });
}

/* =================================================
                SEARCH + STATUS FILTER
================================================= */
function filterData() {
    let filteredData = filterByDateRange(historyData);
    const searchText = searchInput.value.toLowerCase();
    const selectedStatus = statusFilter.value;

    filteredData = filteredData.filter(reading => {
        const searchableText = `${reading.date} ${reading.time} ${reading.mq2} ${reading.mq135} ${reading.temperature} ${reading.humidity} ${reading.score} ${reading.status}`.toLowerCase();
        
        const matchesSearch = searchableText.includes(searchText);
        const matchesStatus = selectedStatus === "all" || reading.status.toLowerCase() === selectedStatus;

        return matchesSearch && matchesStatus;
    });

    displayHistory(filteredData);
}

/* =================================================
                DISPLAY TABLE
================================================= */
function displayHistory(data) {
    tableBody.innerHTML = "";

    if (data.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="8">No readings found for this period</td></tr>`;
        return;
    }

    // Sort newest readings first
    const sortedData = [...data].reverse();

    sortedData.forEach(reading => {
        const row = document.createElement("tr");
        const statusClass = (reading.status || "good").toLowerCase();

        row.innerHTML = `
            <td>${formatDate(reading.date)}</td>
            <td>${reading.time}</td>
            <td>${reading.mq2} ppm</td>
            <td>${reading.mq135} ppm</td>
            <td>${reading.temperature} °C</td>
            <td>${reading.humidity} %</td>
            <td><strong>${reading.score}</strong></td>
            <td><span class="table-status ${statusClass}">${reading.status}</span></td>
        `;
        tableBody.appendChild(row);
    });
}

/* =================================================
                DATE FORMAT
================================================= */
function formatDate(dateString) {
    const date = convertToDate(dateString);
    return date.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
}

/* =================================================
                RANGE LABEL
================================================= */
function updateRangeLabel() {
    const labels = {
        today: "Today's Readings",
        yesterday: "Yesterday's Readings",
        last7days: "Readings from the Last 7 Days",
        last30days: "Readings from the Last 30 Days",
        lastyear: "Readings from the Last Year"
    };
    selectedRangeText.textContent = labels[dateRange.value];
}

/* =================================================
                EVENT LISTENERS
================================================= */
searchInput.addEventListener("input", filterData);
dateRange.addEventListener("change", function () {
    updateRangeLabel();
    filterData();
});
statusFilter.addEventListener("change", filterData);

/* =================================================
                EXPORT CSV
================================================= */
exportButton.addEventListener("click", function () {
    const filteredData = filterByDateRange(historyData);
    let csvContent = "Date,Time,MQ-2 (ppm),MQ-135 (ppm),Temperature (°C),Humidity (%),Air Quality Score,Status\n";

    filteredData.forEach(reading => {
        csvContent += `${reading.date},${reading.time},${reading.mq2},${reading.mq135},${reading.temperature},${reading.humidity},${reading.score},${reading.status}\n`;
    });

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    
    link.href = url;
    link.download = "AQMS_History.csv";
    link.click();
    URL.revokeObjectURL(url);
});

/* =================================================
                INITIAL LOAD
================================================= */
updateRangeLabel();
fetchHistoryData(); // Fetch live records on page launch