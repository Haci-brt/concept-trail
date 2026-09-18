// Left sidebar: vault file tree (with drag & drop and context menu) and tag cloud.
import { openMenu } from "./dialogs.js";
import { icon, logo } from "./icons.js";
import { esc } from "./util.js";

const TAG_LIMIT = 14;

export class Sidebar {
  constructor(root, handlers) {
    this.root = root;
    this.h = handlers;
    this.vaultName = "Vault";
    this.tree = [];
    this.tags = [];
    this.active = null;
    this.expanded = new Set();
    this.vaultOpen = true;
    this.allTags = false;

    root.innerHTML = `
      <div class="sb-icons">
        <button class="icon-btn active" data-act="files" title="Dosyalar">${icon("vault", 17)}</button>
        <span class="grow"></span>
        <button class="icon-btn" data-act="search" title="Not ara (Ctrl+P)">${icon("search", 17)}</button>
        <button class="icon-btn" data-act="refresh" title="Vault'ı yenile">${icon("refresh", 16)}</button>
        <button class="icon-btn" data-act="new-folder" title="Yeni klasör">${icon("folderPlus", 17)}</button>
        <button class="icon-btn" data-act="new-note" title="Yeni not (Ctrl+N)">${icon("filePlus", 17)}</button>
      </div>
      <div class="sb-scroll">
        <div class="sb-section-head collapsible" data-act="toggle-vault" data-drop="">
          ${icon("folder", 16)}<span class="label vault-name"></span><span class="vault-caret">${icon("chevronUp", 15)}</span>
        </div>
        <div class="vtree" role="tree"></div>
        <div class="sb-section-head">
          ${icon("tag", 15)}<span class="label">Etiketler</span>
          <button class="icon-btn sm" data-act="add-tag" title="Nota etiket ekle">${icon("plus", 14)}</button>
        </div>
        <div class="tag-cloud"></div>
      </div>
      <div class="brand-card">
        ${logo(22)}
        <div><div class="t">Fikir Not Defteri</div><div class="s">Yerel. Güvenli. Sadece seninle.</div></div>
      </div>`;
    this.treeEl = root.querySelector(".vtree");
    this.tagsEl = root.querySelector(".tag-cloud");

    root.addEventListener("click", (e) => this._click(e));
    root.addEventListener("contextmenu", (e) => this._context(e));
    this._wireDragAndDrop();
  }

  setTree({ name, tree }) {
    this.vaultName = name;
    this.tree = tree;
    this.render();
  }

  setTags(tags) {
    this.tags = tags;
    this._renderTags();
  }

  setActive(path) {
    this.active = path;
    if (path) this.reveal(path);
    this.render();
  }

  reveal(path) {
    const parts = path.split("/");
    for (let i = 1; i < parts.length; i++) this.expanded.add(parts.slice(0, i).join("/"));
  }

  render() {
    this.root.querySelector(".vault-name").textContent = this.vaultName;
    this.root.querySelector(".vault-caret").innerHTML = icon(this.vaultOpen ? "chevronUp" : "chevronDown", 15);
    this.treeEl.style.display = this.vaultOpen ? "" : "none";
    const rows = [];
    const walk = (items, depth) => {
      for (const item of items) {
        const pad = 6 + depth * 14;
        if (item.type === "dir") {
          const open = this.expanded.has(item.path);
          rows.push(`<div class="vt-row${open ? " open" : ""}" role="treeitem" aria-expanded="${open}" draggable="true"
              data-kind="dir" data-path="${esc(item.path)}" data-drop="${esc(item.path)}" style="padding-left:${pad}px">
            <span class="caret">${icon("chevronRight", 13)}</span>${icon(open ? "folder" : "folder", 16, "kind")}
            <span class="name">${esc(item.name)}</span></div>`);
          if (open) {
            if (item.children.length) walk(item.children, depth + 1);
            else rows.push(`<div class="vt-empty" style="padding-left:${pad + 36}px">Boş klasör</div>`);
          }
        } else {
          rows.push(`<div class="vt-row${item.path === this.active ? " active" : ""}" role="treeitem" draggable="true"
              data-kind="note" data-path="${esc(item.path)}" title="${esc(item.path)}" style="padding-left:${pad + 16}px">
            ${icon("file", 15, "kind")}<span class="name">${esc(item.name)}<span class="ext">.md</span></span></div>`);
        }
      }
    };
    walk(this.tree, 0);
    this.treeEl.innerHTML = rows.join("") ||
      '<div class="vt-empty">Henüz not yok. Sağ üstteki + ile ilk notunu oluştur.</div>';
  }

  _renderTags() {
    const shown = this.allTags ? this.tags : this.tags.slice(0, TAG_LIMIT);
    const hidden = this.tags.length - shown.length;
    this.tagsEl.innerHTML =
      shown.map((t) => `<button class="tag-pill" data-tag="${esc(t.tag)}" title="#${esc(t.tag)} etiketli notlar"># ${esc(t.tag)} <span class="n">${t.count}</span></button>`).join("") +
      (hidden > 0 ? `<button class="tag-pill" data-act="more-tags">+${hidden}</button>` : "") +
      `<button class="tag-pill add" data-act="add-tag" title="Nota etiket ekle">${icon("plus", 13)}</button>`;
  }

  _click(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "search") return this.h.search("");
    if (act === "refresh") return this.h.refresh();
    if (act === "new-note") return this.h.newNote("");
    if (act === "new-folder") return this.h.newFolder("");
    if (act === "add-tag") return this.h.addTag();
    if (act === "more-tags") { this.allTags = true; return this._renderTags(); }
    if (act === "toggle-vault") { this.vaultOpen = !this.vaultOpen; return this.render(); }
    if (act === "files") return;

    const tag = e.target.closest("[data-tag]");
    if (tag) return this.h.search(`#${tag.dataset.tag}`);

    const row = e.target.closest(".vt-row");
    if (!row) return;
    const { kind, path } = row.dataset;
    if (kind === "dir") {
      if (this.expanded.has(path)) this.expanded.delete(path); else this.expanded.add(path);
      this.render();
      this.h.expandedChanged?.();
    } else {
      this.h.open(path);
    }
  }

  _context(e) {
    if (!e.target.closest(".sb-scroll")) return;
    e.preventDefault();
    const row = e.target.closest(".vt-row");
    if (!row) {
      openMenu(e.clientX, e.clientY, [
        { label: "Yeni not", icon: "filePlus", action: () => this.h.newNote("") },
        { label: "Yeni klasör", icon: "folderPlus", action: () => this.h.newFolder("") },
      ]);
      return;
    }
    const { kind, path } = row.dataset;
    const name = row.querySelector(".name").firstChild.textContent;
    const common = [
      { label: "Yeniden adlandır", icon: "rename", action: () => this.h.rename(path, name, kind) },
      "sep",
      { label: "Çöpe taşı", icon: "trash", danger: true, action: () => this.h.trash(path, name, kind) },
    ];
    if (kind === "dir") {
      openMenu(e.clientX, e.clientY, [
        { label: "Bu klasörde yeni not", icon: "filePlus", action: () => this.h.newNote(path) },
        { label: "Alt klasör oluştur", icon: "folderPlus", action: () => this.h.newFolder(path) },
        "sep", ...common,
      ]);
    } else {
      openMenu(e.clientX, e.clientY, [
        { label: "Aç", icon: "file", action: () => this.h.open(path) },
        { label: "Fikir ağacını göster", icon: "tree", action: () => this.h.openTree(path) },
        "sep", ...common,
      ]);
    }
  }

  _wireDragAndDrop() {
    let dragged = null;
    this.root.addEventListener("dragstart", (e) => {
      const row = e.target.closest?.(".vt-row");
      if (!row) return;
      dragged = row.dataset.path;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", dragged);
    });
    this.root.addEventListener("dragend", () => {
      dragged = null;
      this.root.querySelectorAll(".drop").forEach((el) => el.classList.remove("drop"));
    });
    const target = (e) => e.target.closest?.("[data-drop]");
    this.root.addEventListener("dragover", (e) => {
      const t = target(e);
      if (!dragged || !t) return;
      const dir = t.dataset.drop;
      const parent = dragged.includes("/") ? dragged.slice(0, dragged.lastIndexOf("/")) : "";
      if (dir === parent || dir === dragged || dir.startsWith(`${dragged}/`)) return;
      e.preventDefault();
      this.root.querySelectorAll(".drop").forEach((el) => el !== t && el.classList.remove("drop"));
      t.classList.add("drop");
    });
    this.root.addEventListener("dragleave", (e) => target(e)?.classList.remove("drop"));
    this.root.addEventListener("drop", (e) => {
      const t = target(e);
      if (!dragged || !t) return;
      e.preventDefault();
      t.classList.remove("drop");
      this.h.move(dragged, t.dataset.drop);
    });
  }
}
