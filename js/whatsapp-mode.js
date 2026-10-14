/* Cipher WhatsApp mode. Builds its own screen, so index.html needs no extra markup.
   Opens when the sidebar WhatsApp button (id="waBtn") is tapped. */
(function () {
  var QUESTIONS = [
    { t: "Messages today", d: "How many messages came in today.", q: "How many messages did I receive today?", i: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" },
    { t: "Messages per day", d: "Daily totals for the last 7 days.", q: "Show my messages per day for the last 7 days.", i: "M3 3v18h18M7 14l4-4 3 3 5-6" },
    { t: "New contacts", d: "People who messaged you first today.", q: "How many new contacts did I get today?", i: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM19 8v6M22 11h-6" },
    { t: "New contacts this week", d: "First-time contacts, last 7 days.", q: "How many new contacts did I get this week?", i: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" },
    { t: "Busiest chats", d: "Who messaged you the most today.", q: "Who messaged me the most today?", i: "M4 6h16M4 12h16M4 18h10" },
    { t: "Waiting for reply", d: "Chats you haven't answered yet.", q: "Which chats are waiting for my reply?", i: "M12 8v4l3 2M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z" },
    { t: "Auto-replies sent", d: "Welcome replies the bot sent today.", q: "How many auto-replies did the bot send today?", i: "M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" },
    { t: "Channel posts", d: "Posts scheduled while you're offline.", q: "What channel posts are scheduled?", i: "M3 11l18-8v18L3 13v-2ZM11 17v4a2 2 0 0 1-4 0v-3" }
  ];

  var WA_LOGO =
    '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="22" fill="#25d366"/>' +
    '<path d="M24 11a13 13 0 0 0-11 19.8L11 37l6.4-2A13 13 0 1 0 24 11Z" fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/>' +
    '<path d="M19.5 18.5c.6 3.6 4.6 7.7 8.7 8.4l1.6-2-3-1.6-1.2 1c-1.4-.6-2.8-2-3.3-3.4l1-1.2-1.6-3Z" fill="#fff"/></svg>';

  /* Cipher's own logo mark (the same ¢ used in your sidebar and welcome screen) */
  var CIPHER_MARK = '<span class="wa-cmark">&cent;</span>';

  var root, body, msgs, input;

  function build() {
    root = document.createElement("div");
    root.id = "waMode";
    root.setAttribute("aria-label", "WhatsApp mode");
    root.innerHTML =
      '<div class="wa-head">' +
        '<button class="wa-back" aria-label="Back"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg></button>' +
        '<div class="wa-logo">' + WA_LOGO + '</div>' +
        '<div class="wa-title"><b>WhatsApp Control Center</b><span><i></i>Bot online</span></div>' +
        '<div class="wa-power">' + CIPHER_MARK + '<div><small>Powered by</small><b>Cipher</b></div></div>' +
      '</div>' +
      '<div class="wa-body">' +
        '<div class="wa-hero">' + WA_LOGO +
          '<h2>Your WhatsApp at a glance</h2>' +
          '<p>Ask about your messages, new contacts and channel posts, or type your own question.</p></div>' +
        '<div class="wa-quick"><div class="wa-sec">Quick questions <small>Tap to ask</small></div><div class="wa-grid"></div></div>' +
        '<div class="wa-msgs"></div>' +
        '<button class="wa-more" type="button">Show quick questions</button>' +
      '</div>' +
      '<form class="wa-input"><input placeholder="Ask about your WhatsApp..." autocomplete="off">' +
        '<button type="submit" aria-label="Send"><svg viewBox="0 0 24 24"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"/></svg></button></form>';
    document.body.appendChild(root);

    body = root.querySelector(".wa-body");
    msgs = root.querySelector(".wa-msgs");
    input = root.querySelector("input");

    root.querySelector(".wa-grid").innerHTML = QUESTIONS.map(function (x, n) {
      return '<button class="wa-q" data-n="' + n + '"><svg viewBox="0 0 24 24"><path d="' + x.i + '"/></svg><b>' + x.t + "</b><span>" + x.d + "</span></button>";
    }).join("");

    root.querySelector(".wa-grid").addEventListener("click", function (e) {
      var b = e.target.closest(".wa-q");
      if (b) ask(QUESTIONS[b.dataset.n].q);
    });
    root.querySelector(".wa-back").addEventListener("click", close);
    root.querySelector(".wa-more").addEventListener("click", showQuick);
    root.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var v = input.value.trim();
      if (!v) return;
      input.value = "";
      ask(v);
    });
  }

  function open() {
    if (!root) build();
    if (typeof closeSidebar === "function") closeSidebar();
    root.classList.add("open");
  }
  function close() { if (root) root.classList.remove("open"); }

  function showQuick() {
    root.querySelector(".wa-hero").style.display = "";
    root.querySelector(".wa-quick").style.display = "";
    root.querySelector(".wa-more").classList.remove("show");
    body.scrollTop = 0;
  }

  function add(text, who) {
    root.querySelector(".wa-hero").style.display = "none";
    root.querySelector(".wa-quick").style.display = "none";
    root.querySelector(".wa-more").classList.add("show");
    msgs.classList.add("show");
    var d = document.createElement("div");
    d.className = "wa-msg " + who;
    d.textContent = text;
    msgs.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  function ask(question) {
    add(question, "me");
    var bubble = add("...", "bot");
    fetch("/api/whatsapp/ask", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question })
    })
      .then(function (r) {
        return r.json().then(function (j) { return j.answer || "Something went wrong. Try again."; });
      })
      .catch(function () { bubble.textContent = "Can't reach Cipher right now. Check your connection and try again."; return null; })
      .then(function (text) { if (text) bubble.textContent = text; });
  }

  window.openWhatsAppMode = open;
  window.closeWhatsAppMode = close;

  document.addEventListener("click", function (e) {
    if (e.target.closest("#waBtn")) { e.preventDefault(); open(); }
  });
})();
