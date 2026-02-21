// session.js - Shared Hive Keychain session management
// Call initSession() on page load to auto-restore logged-in user

let hiveUser = null;

function initSession() {
    // Check if user is already logged in
    hiveUser = localStorage.getItem('hive_user');
    if (hiveUser) {
        document.getElementById('playerName').value = hiveUser;
        return true;
    }
    return false;
}

function saveSession(username) {
    hiveUser = username;
    localStorage.setItem('hive_user', username);
}

function clearSession() {
    hiveUser = null;
    localStorage.removeItem('hive_user');
}

function getLoggedInUser() {
    return hiveUser || localStorage.getItem('hive_user');
}
