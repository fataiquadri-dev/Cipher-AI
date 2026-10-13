/* ==========================================
   CIPHER SIDEBAR
   Created by Fatai Quadri

   v2 - Claude-style chat history:
   a "Pinned" section on top, "Recents" below,
   a chat icon + one-line title on every row,
   and a "..." menu (Pin / Unpin / Delete) that
   works on phones as well as desktop.
========================================== */

"use strict";

/* ==========================================
   SIDEBAR OBJECT
   NOTE: Sidebar.currentChat mirrors
   Chat.currentChat (defined in chat.js) --
   they are kept in sync everywhere a chat
   is created or selected so nothing silently
   disagrees on "which chat is open".
========================================== */

const Sidebar = {

    opened: false,

    currentChat: null,

    chats: [],

    initialized: false

};


/* ==========================================
   SIDEBAR ELEMENTS
========================================== */

const SidebarUI = {

    sidebar: document.getElementById("sidebar"),

    toggle: document.getElementById("sidebar-toggle"),

    list: document.getElementById("chat-list"),

    newChat: document.querySelector(".new-chat-btn")

};


/* ==========================================
   ICONS (inline SVG so they follow the theme)
========================================== */

const SIDEBAR_ICONS = {

    chat:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 0 1 3 11.5 8.5 8.5 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5Z"/>' +
        '</svg>',

    pin:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M12 17v5"/>' +
        '<path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>' +
        '</svg>',

    dots:
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
        '<circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/>' +
        '</svg>',

    trash:
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>' +
        '</svg>'

};


/* ==========================================
   SMALL HELPERS
========================================== */

function sidebarNotify(message, isError) {

    if (isError) {

        if (typeof showError === "function") {

            showError(message);

        }

    }

    else if (typeof showSuccess === "function") {

        showSuccess(message);

    }

}


/* ==========================================
   EVENTS
========================================== */

function registerSidebarEvents(){

    if(SidebarUI.toggle){

        SidebarUI.toggle.addEventListener(

            "click",

            event => {

                event.stopPropagation();

                toggleSidebar();

            }

        );

    }


    if (SidebarUI.newChat) {

        SidebarUI.newChat.addEventListener(
            "click",
            createNewChat
        );

    }

}


/* ==========================================
   TOGGLE SIDEBAR
========================================== */

function toggleSidebar() {

    Sidebar.opened = !Sidebar.opened;

    SidebarUI.sidebar.classList.toggle(

        "open",

        Sidebar.opened

    );

}


/* ==========================================
   OPEN SIDEBAR
========================================== */

function openSidebar() {

    Sidebar.opened = true;

    SidebarUI.sidebar.classList.add(

        "open"

    );

}


/* ==========================================
   CLOSE SIDEBAR
========================================== */

function closeSidebar() {

    Sidebar.opened = false;

    SidebarUI.sidebar.classList.remove(

        "open"

    );

}


/* ==========================================
   CLOSE WHEN CLICKING OUTSIDE
   (the "..." menu lives outside the sidebar, so
   taps inside it must not count as "outside")
========================================== */

document.addEventListener("click", (event) => {

    if (window.innerWidth > 900) return;

    if (!Sidebar.opened) return;

    const clickedInside =

        SidebarUI.sidebar.contains(event.target) ||

        (SidebarUI.toggle &&
            SidebarUI.toggle.contains(event.target)) ||

        !!(event.target.closest &&
            event.target.closest(".chat-context-menu"));

    if (!clickedInside) {

        closeSidebar();

    }

});


/* ==========================================
   CLOSE AFTER SELECTING CHAT
========================================== */

function closeSidebarAfterSelection() {

    if (window.innerWidth <= 900) {

        closeSidebar();

    }

}


/* ==========================================
   LOAD CHAT LIST
========================================== */

async function loadSidebarChats() {

    try {

        const response = await fetch("/chats");

        if (!response.ok) {

            throw new Error(
                `Server returned ${response.status}`
            );

        }

        const chats = await response.json();

        Sidebar.chats = Array.isArray(chats)
            ? chats
            : [];

        renderSidebarChats(Sidebar.chats);

    }

    catch (error) {

        console.error(
            "Cipher sidebar error:",
            error
        );

        Sidebar.chats = [];

        showSidebarMessage(
            "Unable to load conversations."
        );

    }

}


/* ==========================================
   SHOW SIDEBAR MESSAGE
========================================== */

function showSidebarMessage(message) {

    if (!SidebarUI.list) return;

    SidebarUI.list.innerHTML = `

        <div class="sidebar-empty">

            ${escapeHTML(message)}

        </div>

    `;

}


/* ==========================================
   EMPTY CHAT STATE
========================================== */

function showEmptySidebar() {

    if (!SidebarUI.list) return;

    SidebarUI.list.innerHTML = `

        <div class="sidebar-empty">

            <p>No conversations yet.</p>

            <span>
                Start a new conversation with Cipher.
            </span>

        </div>

    `;

}


/* ==========================================
   SELECT CHAT
========================================== */

async function selectSidebarChat(chatId) {

    if (!chatId) return;

    Sidebar.currentChat = chatId;

    closeSidebarAfterSelection();

    if (typeof loadChat === "function") {

        await loadChat(chatId);

    }

    highlightActiveChat(chatId);

}


/* ==========================================
   ACTIVE CHAT
========================================== */

function highlightActiveChat(chatId) {

    document
        .querySelectorAll(".chat-item")
        .forEach(item => {

            item.classList.toggle(

                "active",

                String(item.dataset.id) ===
                String(chatId)

            );

        });

}


/* ==========================================
   RENDER SIDEBAR CHATS
   Pinned chats first, then "Recents" --
   laid out the same way as Claude's sidebar.
========================================== */

function renderSidebarChats(chats) {

    if (!SidebarUI.list) return;

    SidebarUI.list.innerHTML = "";

    if (!chats || chats.length === 0) {

        showEmptySidebar();

        return;

    }

    const pinned = chats.filter(
        chat => chat.pinned
    );

    const recent = chats.filter(
        chat => !chat.pinned
    );

    if (pinned.length > 0) {

        addSidebarSectionLabel(
            "Pinned",
            SIDEBAR_ICONS.pin
        );

        pinned.forEach(chat => {

            SidebarUI.list.appendChild(
                createSidebarChatItem(chat)
            );

        });

    }

    if (recent.length > 0) {

        addSidebarSectionLabel("Recents");

        recent.forEach(chat => {

            SidebarUI.list.appendChild(
                createSidebarChatItem(chat)
            );

        });

    }

}


/* ==========================================
   SECTION LABEL
========================================== */

function addSidebarSectionLabel(label, iconHTML) {

    const section = document.createElement("div");

    section.className =
        "chat-section-label";

    if (iconHTML) {

        const icon = document.createElement("span");

        icon.className = "chat-section-icon";

        icon.innerHTML = iconHTML;

        section.appendChild(icon);

    }

    const text = document.createElement("span");

    text.textContent = label;

    section.appendChild(text);

    SidebarUI.list.appendChild(section);

}


/* ==========================================
   CREATE CHAT ITEM
   [chat icon] [one-line title ...]  [...]
========================================== */

function createSidebarChatItem(chat) {

    const item = document.createElement("div");

    item.className = "chat-item";

    item.dataset.id = chat.id;

    if (
        String(chat.id) ===
        String(Sidebar.currentChat)
    ) {

        item.classList.add("active");

    }


    const icon = document.createElement("span");

    icon.className = "chat-item-icon";

    icon.innerHTML = SIDEBAR_ICONS.chat;


    const titleEl = document.createElement("div");

    titleEl.className = "chat-item-title";

    titleEl.textContent =
        chat.title ||
        "New Conversation";

    titleEl.title = titleEl.textContent;


    const actions = document.createElement("div");

    actions.className = "chat-item-actions";

    const menuButton = document.createElement("button");

    menuButton.type = "button";

    menuButton.className = "chat-action-btn";

    menuButton.title = "More options";

    menuButton.setAttribute("aria-label", "More options");

    menuButton.innerHTML = SIDEBAR_ICONS.dots;

    menuButton.addEventListener(
        "click",
        event => openChatMenu(event, chat.id)
    );

    actions.appendChild(menuButton);


    item.append(icon, titleEl, actions);


    item.addEventListener(
        "click",
        () => selectSidebarChat(chat.id)
    );

    /* Right-click on desktop / long-press on phones */
    item.addEventListener(
        "contextmenu",
        event => {

            event.preventDefault();

            openChatMenu(event, chat.id, menuButton);

        }
    );

    return item;

}


/* ==========================================
   CHAT DATE
========================================== */

function formatChatDate(dateValue) {

    if (!dateValue) return "";

    const date =
        new Date(dateValue);

    if (Number.isNaN(date.getTime())) {

        return "";

    }

    const now = new Date();

    const difference =
        now.getTime() -
        date.getTime();

    const oneDay =
        24 * 60 * 60 * 1000;

    if (difference < oneDay) {

        return "Today";

    }

    if (difference < oneDay * 2) {

        return "Yesterday";

    }

    return date.toLocaleDateString(
        undefined,
        {
            month: "short",
            day: "numeric"
        }
    );

}


/* ==========================================
   CHAT SEARCH (uses the existing #chat-search
   input already in index.html -- no need to
   create a duplicate one)
========================================== */

function searchSidebarChats(query) {

    query = query.trim().toLowerCase();

    if (!query) {

        renderSidebarChats(Sidebar.chats);

        return;

    }

    const results = Sidebar.chats.filter(chat => {

        const title =
            String(chat.title || "").toLowerCase();

        return title.includes(query);

    });

    renderSidebarSearchResults(results, query);

}


function renderSidebarSearchResults(chats, query) {

    if (!SidebarUI.list) return;

    SidebarUI.list.innerHTML = "";

    if (chats.length === 0) {

        SidebarUI.list.innerHTML = `

            <div class="sidebar-empty">

                <p>No chats found.</p>

                <span>
                    No conversation matches
                    "${escapeHTML(query)}".
                </span>

            </div>

        `;

        return;

    }

    addSidebarSectionLabel(
        `Search results (${chats.length})`
    );

    chats.forEach(chat => {

        SidebarUI.list.appendChild(
            createSidebarChatItem(chat)
        );

    });

}


function setupChatSearchEvents() {

    const searchInput =
        document.getElementById(
            "chat-search"
        );

    if (!searchInput) return;

    searchInput.addEventListener(
        "input",
        () => {

            searchSidebarChats(
                searchInput.value
            );

        }
    );

}


/* ==========================================
   CHAT OPTIONS MENU  (Pin / Unpin / Delete)
========================================== */

let activeChatMenu = null;


function openChatMenu(event, chatId, anchor) {

    event.stopPropagation();

    closeChatMenu();

    const button = anchor || event.currentTarget;

    const chat = Sidebar.chats.find(
        item => String(item.id) === String(chatId)
    );

    if (!chat) return;


    const menu = document.createElement("div");

    menu.className = "chat-context-menu";

    menu.setAttribute("role", "menu");


    const pinButton = document.createElement("button");

    pinButton.type = "button";

    pinButton.innerHTML =
        SIDEBAR_ICONS.pin +
        `<span>${chat.pinned ? "Unpin chat" : "Pin chat"}</span>`;

    pinButton.addEventListener(
        "click",
        () => togglePinChat(chatId)
    );


    const deleteButton = document.createElement("button");

    deleteButton.type = "button";

    deleteButton.className = "danger";

    deleteButton.innerHTML =
        SIDEBAR_ICONS.trash +
        "<span>Delete</span>";

    deleteButton.addEventListener(
        "click",
        () => deleteChat(chatId)
    );


    menu.append(pinButton, deleteButton);

    document.body.appendChild(menu);


    /* Position under the button, flipping upward and
       sideways if it would run off the screen. */

    const rect = button.getBoundingClientRect();

    const menuRect = menu.getBoundingClientRect();

    let top = rect.bottom + 6;

    if (top + menuRect.height > window.innerHeight - 8) {

        top = Math.max(8, rect.top - menuRect.height - 6);

    }

    const left = Math.min(
        Math.max(8, rect.right - menuRect.width),
        window.innerWidth - menuRect.width - 8
    );

    menu.style.top = `${top}px`;

    menu.style.left = `${left}px`;

    activeChatMenu = menu;

}


function closeChatMenu() {

    if (activeChatMenu) {

        activeChatMenu.remove();

        activeChatMenu = null;

    }

}


document.addEventListener(
    "click",
    closeChatMenu
);


/* ==========================================
   PIN / UNPIN CHAT
========================================== */

async function togglePinChat(chatId) {

    closeChatMenu();

    const chat = Sidebar.chats.find(
        item => String(item.id) === String(chatId)
    );

    const wasPinned = !!(chat && chat.pinned);

    try {

        const response = await fetch(

            `/chats/${encodeURIComponent(chatId)}/pin`,

            {
                method: "POST"
            }

        );

        if (!response.ok) {

            throw new Error(
                "Unable to update pin status."
            );

        }

        await loadSidebarChats();

        highlightActiveChat(Sidebar.currentChat);

        sidebarNotify(
            wasPinned ? "Chat unpinned." : "Chat pinned."
        );

    }

    catch (error) {

        console.error(error);

        sidebarNotify(
            "Unable to update chat.",
            true
        );

    }

}


/* ==========================================
   DELETE CHAT
========================================== */

async function deleteChat(chatId) {

    closeChatMenu();

    const confirmed = confirm(
        "Delete this conversation?"
    );

    if (!confirmed) return;

    try {

        const response = await fetch(

            `/chats/${encodeURIComponent(chatId)}/delete`,

            {
                method: "POST"
            }

        );

        if (!response.ok) {

            throw new Error(
                "Unable to delete chat."
            );

        }

        if (
            String(Sidebar.currentChat) ===
            String(chatId)
        ) {

            Sidebar.currentChat = null;

            if (typeof Chat !== "undefined") {

                Chat.currentChat = null;

                Chat.messages = [];

            }

            if (
                typeof showWelcomeScreen ===
                "function"
            ) {

                showWelcomeScreen();

            }

        }

        await loadSidebarChats();

        sidebarNotify(
            "Conversation deleted."
        );

    }

    catch (error) {

        console.error(error);

        sidebarNotify(
            "Unable to delete conversation.",
            true
        );

    }

}


/* ==========================================
   NEW CHAT
   This is the single implementation (chat.js
   no longer defines its own createNewChat, so
   there's nothing to silently overwrite).
========================================== */

async function createNewChat() {

    try {

        const response = await fetch(
            "/chats/new",
            {
                method: "POST"
            }
        );

        if (!response.ok) {

            throw new Error(
                "Unable to create chat."
            );

        }

        const chat = await response.json();

        Sidebar.currentChat = chat.id;

        if (typeof Chat !== "undefined") {

            Chat.currentChat = chat.id;

            Chat.messages = [];

        }

        if (
            typeof showWelcomeScreen ===
            "function"
        ) {

            showWelcomeScreen();

        }

        await loadSidebarChats();

        highlightActiveChat(chat.id);

        closeSidebarAfterSelection();

        if (
            typeof ChatUI !== "undefined" &&
            ChatUI.input
        ) {

            ChatUI.input.focus();

        }

    }

    catch (error) {

        console.error(
            "New chat error:",
            error
        );

        sidebarNotify(
            "Unable to create a new chat.",
            true
        );

    }

}


/*
 * index.html calls startNewChat() in a couple
 * of inline onclick attributes -- keep that name
 * working as an alias for createNewChat().
 */

function startNewChat() {

    createNewChat();

}


/* ==========================================
   FINAL SIDEBAR INITIALIZATION
========================================== */

function initializeSidebar() {

    if (Sidebar.initialized) return;

    Sidebar.initialized = true;

    setupChatSearchEvents();

    registerSidebarEvents();

    loadSidebarChats();

}


/* ==========================================
   WINDOW RESIZE
========================================== */

window.addEventListener(
    "resize",
    () => {

        if (window.innerWidth > 900) {

            closeSidebar();

        }

    }
);


/* ==========================================
   ESCAPE KEY
========================================== */

document.addEventListener(
    "keydown",
    event => {

        if (event.key !== "Escape") return;

        closeChatMenu();

        if (
            window.innerWidth <= 900 &&
            Sidebar.opened
        ) {

            closeSidebar();

        }

    }
);


/* ==========================================
   START SIDEBAR AFTER PAGE LOAD
========================================== */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        initializeSidebar();

    }
);


/* ==========================================
   EXPOSE SIDEBAR
========================================== */

window.CipherSidebar = Sidebar;

/* ==========================================
   END OF SIDEBAR.JS
========================================== */
