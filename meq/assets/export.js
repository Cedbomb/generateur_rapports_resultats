
(function () {
"use strict";

/* Sélecteur des conteneurs à équiper, posé par la page avant ce script. */
const CIBLES = window.EXPORT_CIBLES || ".chart-wrap";

/* Géométrie de la composition, en pixels CSS : le contexte est mis à
   l'échelle une fois pour toutes, tout le reste du code raisonne en CSS. */
const MARGE = 16;
const GAP = 12;
/* Le titre au fil des filtres, promu titre principal, est agrandi d'une
   fois et demie par rapport à la ligne discrète qu'il occupait avant
   (12,5 px), interligne compris. */
const TAILLE_TITRE = 18.75;
const H_TITRE = 27;
const H_SOUS = 16;
const H_LIGNE_LEG = 19;
const LARGEUR_CLE = 20;
const GAP_CLE = 7;
const GAP_ITEM = 20;
const LARGEUR_MIN = 380;
const FOND = "#ffffff";

const POLICE = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";

/* ---------------- Repérage du tracé ---------------- */

function estVisible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
}

/* Un graphique sans donnée affiche son voile « Sélectionnez… / Aucune
   donnée » PAR-DESSUS un canevas d'axes vides : le canevas existe, il n'y a
   simplement rien à exporter. On le détecte par le voile plutôt que par les
   données, que ce module ne connaît pas. */
function estVide(cible) {
    const corps = cible.closest(".panel-body") || cible.parentElement;
    const voiles = Array.from(cible.querySelectorAll(".chart-empty"));
    if (corps) voiles.push.apply(voiles, Array.from(corps.querySelectorAll(".section-vide")));
    return voiles.some(v => !v.hidden && getComputedStyle(v).display !== "none");
}

/* Règles de la feuille du document qui habillent l'INTÉRIEUR d'un SVG
   (« .meq-svg .axe », « .meq-svg text »…). Hors du document, un SVG sérialisé
   perd ces couleurs : il faut les lui embarquer.

   Les règles qui visent la RACINE elle-même (« .meq-svg { max-width:100%;
   height:auto } ») sont volontairement écartées : dans une image autonome
   elles se mesureraient contre la fenêtre de l'image et non contre la page,
   et écraseraient les dimensions qu'on vient de fixer. */
function reglesInternes(svg) {
    const classes = Array.from(svg.classList).map(c => "." + c);
    if (!classes.length) return "";
    const out = [];
    for (const feuille of Array.from(document.styleSheets)) {
        let regles = null;
        try { regles = feuille.cssRules; } catch (e) { continue; }  // feuille d'une autre origine
        if (!regles) continue;
        for (const r of Array.from(regles)) {
            if (!r.selectorText || !r.style) continue;
            const garde = r.selectorText.split(",").map(s => s.trim()).filter(
                s => classes.some(c => s.indexOf(c) === 0) && /[\s>+~]/.test(s));
            if (garde.length) out.push(garde.join(", ") + " {" + r.style.cssText + "}");
        }
    }
    return out.join("\n");
}

function imageDepuisSvg(svg, largeur, hauteur, densite) {
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    /* Dimensions en pixels de SORTIE : le rastérisateur du navigateur suit
       les attributs width/height du SVG, c'est là que se gagne la finesse. */
    clone.setAttribute("width", String(Math.round(largeur * densite)));
    clone.setAttribute("height", String(Math.round(hauteur * densite)));
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = reglesInternes(svg);
    clone.insertBefore(style, clone.firstChild);
    const texte = new XMLSerializer().serializeToString(clone);
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(texte);
    return new Promise(function (resolve, reject) {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("SVG illisible"));
        img.src = url;
    });
}

/* Retourne { largeur, hauteur, densite, peindre(ctx, x, y) } en pixels CSS,
   ou null si le graphique n'est pas tracé (section repliée, mode de page
   masqué, aucune donnée). */
async function preparerSource(cible) {
    if (estVide(cible)) return null;

    const toiles = Array.from(cible.querySelectorAll("canvas")).filter(estVisible);
    if (toiles.length) {
        const rects = toiles.map(c => c.getBoundingClientRect());
        let g = Infinity, h = Infinity, d = -Infinity, b = -Infinity;
        for (const r of rects) {
            g = Math.min(g, r.left); h = Math.min(h, r.top);
            d = Math.max(d, r.right); b = Math.max(b, r.bottom);
        }
        /* Densité RÉELLE du canevas (uPlot trace à devicePixelRatio) : on
           compose à celle-là pour recopier les pixels un pour un. Composer
           plus haut ne ferait qu'agrandir un tracé déjà pixellisé. */
        const densite = Math.max(1, toiles[0].width / Math.max(1, rects[0].width));
        return {
            largeur: d - g,
            hauteur: b - h,
            densite: densite,
            /* Position à l'écran du coin haut-gauche : sert à recomposer
               plusieurs sources dans leur disposition d'origine (voir
               composerGroupe). */
            rect: { left: g, top: h },
            peindre(ctx, x, y) {
                for (let i = 0; i < toiles.length; i++) {
                    const r = rects[i];
                    ctx.drawImage(toiles[i], x + (r.left - g), y + (r.top - h), r.width, r.height);
                }
            },
        };
    }

    const svg = Array.from(cible.querySelectorAll("svg")).filter(estVisible)[0];
    if (svg) {
        const r = svg.getBoundingClientRect();
        /* Le SVG est vectoriel : rien n'oblige à s'en tenir à la densité de
           l'écran, on le rastérise à 2× pour une image nette à l'impression. */
        const densite = Math.max(2, window.devicePixelRatio || 1);
        const img = await imageDepuisSvg(svg, r.width, r.height, densite);
        return {
            largeur: r.width,
            hauteur: r.height,
            densite: densite,
            rect: { left: r.left, top: r.top },
            peindre(ctx, x, y) { ctx.drawImage(img, x, y, r.width, r.height); },
        };
    }
    return null;
}

/* ---------------- Titres et légende, lus dans le DOM ---------------- */

/* Deux lignes au-dessus du tracé : en TITRE, le titre au fil des filtres que
   le rapport recalcule à chaque reconstruction (.chart-live-title, posé par
   setLiveTitle() : « CSS — Français — Sommaire — Moyenne (%) ») ; en
   petit, le titre de la PAGE.

   Le nom de la SECTION (« Résultats par cours (barres) — une matière ») ne
   figure plus : il dit d'où l'image vient, pas ce qu'elle montre, et la
   place revient à la seule ligne qui décrive le tracé. Il reste toutefois
   le repli là où il n'y a pas de titre au fil des filtres — les nuages des
   rapports par élève et des épreuves ministérielles —, faute de quoi ces
   images-là n'auraient plus d'identification du tout.

   Le qualificatif du SOUS-GRAPHIQUE (« Primaire » / « Secondaire ») est en
   revanche conservé, en tête : les deux vues d'une paire de vues partagent
   leur titre au fil des filtres au mot près (voir les appels setLiveTitle()
   des vues), et rien d'autre ne distinguerait leurs deux images — ni
   leurs deux noms de fichier. Il tombe en revanche avec
   `{ sousTitre: false }` — le cas d'une diapositive PowerPoint qui réunit
   les DEUX sous-graphiques : le qualificatif y est porté par chaque moitié
   de l'image, et non par le titre commun.

   La diapositive PowerPoint, elle, reprend la hiérarchie du rapport : en
   titre le nom de la SECTION (`section`), en sous-titre le titre au fil des
   filtres, qualificatif compris (`fil`). */
function titres(cible, options) {
    const panneau = cible.closest("details.panel");
    const sommaire = panneau ? panneau.querySelector("summary") : null;
    const section = sommaire ? sommaire.textContent.trim().replace(/\s+/g, " ") : "";
    const sous = cible.closest(".subplot");
    const sousTitre = sous ? sous.querySelector(".subplot-title") : null;
    const direct = cible.querySelector(".chart-live-title");
    let fil = direct ? direct.textContent.trim().replace(/\s+/g, " ") : "";
    /* Sans titre au fil des filtres, l'intitulé posé JUSTE AVANT la rangée
       en tient lieu : c'est le libellé d'un objectif du panneau « Projet
       éducatif par école » (generateur_classe.py), où chaque rangée a sa
       propre matière et sa propre compétence. Sans lui, toutes les
       diapositives de ce panneau portaient le même titre (la section). */
    if (!fil) {
        const rangee = cible.closest(".subplot-row");
        const avant = rangee ? rangee.previousElementSibling : null;
        if (avant && avant.classList.contains("subplot-title")) {
            fil = avant.textContent.trim().replace(/\s+/g, " ");
        }
    }
    let titre = fil || section;
    if (sousTitre && (!options || options.sousTitre !== false)) {
        const s = sousTitre.textContent.trim();
        titre = titre ? s + " — " + titre : s;
        fil = fil ? s + " — " + fil : s;
    }
    return { titre: titre || document.title, page: document.title, section: section, fil: fil };
}

/* La légende d'un graphique est le premier bloc de légende de SA section —
   les deux sous-graphiques côte à côte de la page en partagent une
   seule, ce qui est exactement ce qu'on veut dans les deux images.

   Les couleurs sont lues dans le style CALCULÉ des clés : fond plein pour
   une pastille (barres), couleur de bordure haute pour un trait (courbes),
   pointillé si la bordure l'est. Ce module reste ainsi étranger aux données
   comme aux palettes de chaque rapport. */
function legende(cible) {
    const corps = cible.closest(".panel-body") || cible.parentElement;
    if (!corps) return [];
    const boite = corps.querySelector(".chart-legend, .classe-legende, .legende");
    if (!boite) return [];
    const out = [];
    for (const item of Array.from(boite.children)) {
        const texte = (item.textContent || "").trim().replace(/\s+/g, " ");
        if (!texte) continue;
        const cle = item.querySelector(".legend-key, i");
        if (!cle) { out.push({ texte: texte, forme: "texte" }); continue; }
        const cs = getComputedStyle(cle);
        const fond = cs.backgroundColor;
        const plein = fond && fond !== "transparent"
                      && !/^rgba\(\s*0,\s*0,\s*0,\s*0\s*\)$/.test(fond);
        out.push(plein
            ? { texte: texte, forme: "pastille", couleur: fond }
            : { texte: texte, forme: "trait", couleur: cs.borderTopColor || "#52514e",
                tirets: cs.borderTopStyle === "dashed" });
    }
    return out;
}

/* ---------------- Composition et téléchargement ---------------- */

function largeurItem(ctx, it) {
    return (it.forme === "texte" ? 0 : LARGEUR_CLE + GAP_CLE) + ctx.measureText(it.texte).width;
}

/* Un titre au fil des filtres peut être long (plusieurs matières, plusieurs
   cours, un sous-groupe). On le REPLIE sur la largeur de l'image plutôt que
   d'élargir celle-ci au gré de la sélection : deux exports du même
   graphique gardent ainsi le même format. Les titres sont ponctués de
   « — » entouré d'espaces, la coupure aux espaces tombe donc juste. */
function couperTexte(ctx, texte, largeur, police) {
    ctx.font = police;
    if (ctx.measureText(texte).width <= largeur) return [texte];
    const lignes = [];
    let courante = "";
    for (const mot of texte.split(" ")) {
        const essai = courante ? courante + " " + mot : mot;
        if (courante && ctx.measureText(essai).width > largeur) {
            lignes.push(courante);
            courante = mot;
        } else {
            courante = essai;
        }
    }
    if (courante) lignes.push(courante);
    return lignes;
}

/* Découpe la légende en lignes tenant dans `largeur`, en conservant la
   mesure de chaque entrée pour ne pas la refaire au tracé. */
function disposerLegende(ctx, items, largeur) {
    const lignes = [];
    let ligne = [];
    let x = 0;
    for (const it of items) {
        const l = largeurItem(ctx, it);
        if (ligne.length && x + l > largeur) { lignes.push(ligne); ligne = []; x = 0; }
        ligne.push({ item: it, largeur: l });
        x += l + GAP_ITEM;
    }
    if (ligne.length) lignes.push(ligne);
    return lignes;
}

function peindreLegende(ctx, lignes, x0, y0) {
    ctx.font = "12px " + POLICE;
    ctx.textBaseline = "middle";
    let y = y0;
    for (const ligne of lignes) {
        let x = x0;
        const milieu = y + H_LIGNE_LEG / 2;
        for (const entree of ligne) {
            const it = entree.item;
            let xTexte = x;
            if (it.forme === "pastille") {
                ctx.fillStyle = it.couleur;
                ctx.fillRect(x, milieu - 5, LARGEUR_CLE - 4, 10);
                xTexte = x + LARGEUR_CLE + GAP_CLE;
            } else if (it.forme === "trait") {
                ctx.strokeStyle = it.couleur;
                ctx.lineWidth = 3;
                ctx.setLineDash(it.tirets ? [4, 3] : []);
                ctx.beginPath();
                ctx.moveTo(x, milieu);
                ctx.lineTo(x + LARGEUR_CLE - 2, milieu);
                ctx.stroke();
                ctx.setLineDash([]);
                xTexte = x + LARGEUR_CLE + GAP_CLE;
            }
            ctx.fillStyle = "#52514e";
            ctx.fillText(it.texte, xTexte, milieu);
            x += entree.largeur + GAP_ITEM;
        }
        y += H_LIGNE_LEG;
    }
}

/* Le nom du fichier reprend le titre, qui porte la sélection : sans elle,
   exporter le même graphique sous trois filtres produirait trois fois le
   même nom, et le navigateur les numéroterait « (1) », « (2) » sans dire
   lequel est lequel. */
function nomFichier(titre, extension) {
    const base = titre
        .normalize("NFD").replace(/[̀-ͯ]/g, "")
        .replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
        .slice(0, 90).toLowerCase() || "graphique";
    const d = new Date();
    const p = n => String(n).padStart(2, "0");
    return base + "_" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + (extension || ".png");
}

/* Compose l'image d'un graphique sur un canevas hors écran. Avec
   `entete: false`, titre et sous-titre sont omis : la diapositive PowerPoint
   porte le titre en texte modifiable, l'image ne le répète pas. Retourne
   { canvas, largeur, hauteur, titre } (dimensions en pixels CSS) ou null. */
async function composer(cible, options) {
    const src = await preparerSource(cible);
    if (!src) return null;
    return composerSource(src, titres(cible), legende(cible),
                          !options || options.entete !== false);
}

/* Réunit les sous-graphiques d'une même rangée (.subplot-row : « Primaire »
   et « Secondaire », nuage + progression du rapport par élève) en UNE
   image, chacun à sa place et sous son propre intertitre, comme à l'écran.
   Les deux ne se lisent que l'un par l'autre — même sélection, même légende,
   souvent la même échelle — et les séparer en deux diapositives casserait la
   comparaison. Le titre commun est celui de la rangée, sans qualificatif. */
async function composerGroupe(cibles) {
    const parts = [];
    for (const cible of cibles) {
        const src = await preparerSource(cible);
        if (!src) continue;                       // sous-graphique vide : omis
        const sous = cible.closest(".subplot");
        const h3 = sous ? sous.querySelector(".subplot-title") : null;
        parts.push({
            src: src,
            titre: h3 ? h3.textContent.trim().replace(/\s+/g, " ") : "",
            rectTitre: h3 && h3.getClientRects().length ? h3.getBoundingClientRect() : null,
        });
    }
    if (!parts.length) return null;

    /* La boîte du groupe est l'enveloppe des tracés ET de leurs intertitres,
       en coordonnées d'écran : les positions relatives sont ainsi celles de
       la page, quelle que soit la disposition de la rangée (côte à côte pour
       les classements, empilée pour les objectifs). */
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const p of parts) {
        x0 = Math.min(x0, p.src.rect.left);
        y0 = Math.min(y0, p.src.rect.top);
        x1 = Math.max(x1, p.src.rect.left + p.src.largeur);
        y1 = Math.max(y1, p.src.rect.top + p.src.hauteur);
        if (p.rectTitre) {
            x0 = Math.min(x0, p.rectTitre.left);
            y0 = Math.min(y0, p.rectTitre.top);
            x1 = Math.max(x1, p.rectTitre.right);
            y1 = Math.max(y1, p.rectTitre.bottom);
        }
    }

    const groupe = {
        largeur: x1 - x0,
        hauteur: y1 - y0,
        densite: Math.max.apply(null, parts.map(p => p.src.densite)),
        rect: { left: x0, top: y0 },
        peindre(ctx, x, y) {
            for (const p of parts) {
                if (p.rectTitre && p.titre) {
                    ctx.save();
                    ctx.font = "600 13px " + POLICE;
                    ctx.fillStyle = "#0b0b0b";
                    ctx.textBaseline = "middle";
                    ctx.fillText(p.titre, x + (p.rectTitre.left - x0),
                                 y + (p.rectTitre.top - y0) + p.rectTitre.height / 2);
                    ctx.restore();
                }
                p.src.peindre(ctx, x + (p.src.rect.left - x0), y + (p.src.rect.top - y0));
            }
        },
    };
    return composerSource(groupe, titres(cibles[0], { sousTitre: false }),
                          legende(cibles[0]), false);
}

function composerSource(src, t, items, avecEntete) {
    const mesure = document.createElement("canvas").getContext("2d");
    mesure.font = "12px " + POLICE;
    /* Une entrée de légende plus large que le tracé (un nom d'école long, la
       mention d'échelle) élargit l'image plutôt que d'en déborder.
       Les titres, eux, se replient : voir couperTexte(). */
    let largeurContenu = Math.max(src.largeur, LARGEUR_MIN);
    for (const it of items) largeurContenu = Math.max(largeurContenu, largeurItem(mesure, it));
    const lignesLeg = items.length ? disposerLegende(mesure, items, largeurContenu) : [];

    const entete = [
        { texte: t.titre, police: "600 " + TAILLE_TITRE + "px " + POLICE,
          couleur: "#0b0b0b", h: H_TITRE },
        { texte: t.page, police: "11px " + POLICE, couleur: "#898781", h: H_SOUS },
    ].filter(b => avecEntete && b.texte);
    for (const b of entete) b.lignes = couperTexte(mesure, b.texte, largeurContenu, b.police);

    const hauteurEntete = entete.reduce((n, b) => n + b.lignes.length * b.h, 0);
    const hauteurLeg = lignesLeg.length ? GAP + lignesLeg.length * H_LIGNE_LEG : 0;
    const largeur = largeurContenu + MARGE * 2;
    const hauteur = MARGE + hauteurEntete + (entete.length ? GAP : 0)
                    + src.hauteur + hauteurLeg + MARGE;

    const s = src.densite;
    const sortie = document.createElement("canvas");
    sortie.width = Math.round(largeur * s);
    sortie.height = Math.round(hauteur * s);
    const ctx = sortie.getContext("2d");
    ctx.setTransform(s, 0, 0, s, 0, 0);
    ctx.fillStyle = FOND;
    ctx.fillRect(0, 0, largeur, hauteur);

    let y = MARGE;
    ctx.textBaseline = "middle";
    for (const b of entete) {
        ctx.font = b.police;
        ctx.fillStyle = b.couleur;
        for (const ligne of b.lignes) {
            ctx.fillText(ligne, MARGE, y + b.h / 2);
            y += b.h;
        }
    }
    if (entete.length) y += GAP;

    src.peindre(ctx, MARGE, y);
    y += src.hauteur;

    if (lignesLeg.length) peindreLegende(ctx, lignesLeg, MARGE, y + GAP);

    return { canvas: sortie, largeur: largeur, hauteur: hauteur, titre: t.titre, titres: t };
}

function telecharger(blob, nom) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nom;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function enBlob(canvas) {
    return new Promise(resolve => canvas.toBlob(resolve, "image/png"));
}

async function exporter(cible) {
    const image = await composer(cible);
    if (!image) return false;
    const blob = await enBlob(image.canvas);
    if (blob) telecharger(blob, nomFichier(image.titre));
    return true;
}

/* ---------------- Pose des boutons ---------------- */

function clignote(bouton, message) {
    const initial = bouton.dataset.libelle;
    bouton.textContent = message;
    bouton.disabled = true;
    setTimeout(function () {
        bouton.textContent = initial;
        bouton.disabled = false;
    }, 1400);
}

function installer() {
    for (const cible of Array.from(document.querySelectorAll(CIBLES))) {
        if (cible.querySelector(":scope > .export-png-btn")) continue;
        cible.classList.add("export-anchor");
        const bouton = document.createElement("button");
        bouton.type = "button";
        bouton.className = "export-png-btn";
        bouton.dataset.libelle = "↓ PNG";
        bouton.textContent = bouton.dataset.libelle;
        bouton.title = "Télécharger ce graphique en image PNG, tel qu'il est affiché";
        bouton.setAttribute("aria-label", "Exporter ce graphique en image PNG");
        bouton.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            exporter(cible).then(function (ok) {
                if (!ok) clignote(bouton, "vide");
            }).catch(function () {
                clignote(bouton, "échec");
            });
        });
        cible.appendChild(bouton);
    }
    installerBoutonPptx();
}

/* ================= Écrivain .pptx minimal =================
   Un .pptx est une archive zip de parties XML. On n'y met que ce que
   PowerPoint exige pour ouvrir le fichier sans proposer de « réparation » :
   un masque, une disposition vide, un thème complet, et une diapositive par
   image. Les PNG étant déjà compressés, l'archive est écrite sans compression
   (méthode STORE) : ni bibliothèque zip, ni deflate à embarquer. */

const TABLE_CRC = (function () {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        t[n] = c >>> 0;
    }
    return t;
})();

function crc32(octets) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < octets.length; i++) c = TABLE_CRC[(c ^ octets[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
}

/* fichiers : [{ nom, octets }] où octets est une chaîne (encodée en UTF-8)
   ou un Uint8Array. */
function zipStore(fichiers, type) {
    const utf8 = new TextEncoder();
    const d = new Date();
    const heure = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const jour = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    const locaux = [];
    const central = [];
    let decalage = 0;
    let tailleCentral = 0;
    for (const f of fichiers) {
        const nom = utf8.encode(f.nom);
        const octets = typeof f.octets === "string" ? utf8.encode(f.octets) : f.octets;
        const crc = crc32(octets);

        const l = new DataView(new ArrayBuffer(30));
        l.setUint32(0, 0x04034b50, true);
        l.setUint16(4, 20, true);
        l.setUint16(6, 0x0800, true);      // noms en UTF-8
        l.setUint16(8, 0, true);           // STORE
        l.setUint16(10, heure, true);
        l.setUint16(12, jour, true);
        l.setUint32(14, crc, true);
        l.setUint32(18, octets.length, true);
        l.setUint32(22, octets.length, true);
        l.setUint16(26, nom.length, true);
        locaux.push(l, nom, octets);

        const c = new DataView(new ArrayBuffer(46));
        c.setUint32(0, 0x02014b50, true);
        c.setUint16(4, 20, true);
        c.setUint16(6, 20, true);
        c.setUint16(8, 0x0800, true);
        c.setUint16(10, 0, true);
        c.setUint16(12, heure, true);
        c.setUint16(14, jour, true);
        c.setUint32(16, crc, true);
        c.setUint32(20, octets.length, true);
        c.setUint32(24, octets.length, true);
        c.setUint16(28, nom.length, true);
        c.setUint32(42, decalage, true);
        central.push(c, nom);

        decalage += 30 + nom.length + octets.length;
        tailleCentral += 46 + nom.length;
    }
    const fin = new DataView(new ArrayBuffer(22));
    fin.setUint32(0, 0x06054b50, true);
    fin.setUint16(8, fichiers.length, true);
    fin.setUint16(10, fichiers.length, true);
    fin.setUint32(12, tailleCentral, true);
    fin.setUint32(16, decalage, true);
    return new Blob(locaux.concat(central, [fin]), { type: type });
}

const XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
const NS_PPT = ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    + ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    + ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"';
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";
const CT_PML = "application/vnd.openxmlformats-officedocument.presentationml.";

/* Diapositive 16:9, en EMU (914 400 par pouce). */
const EMU_L = 12192000;
const EMU_H = 6858000;
const EMU_MARGE = 365760;

function echapperXml(texte) {
    return String(texte == null ? "" : texte)
        /* Caractères de contrôle interdits en XML 1.0 (sauf tab, LF, CR). */
        .split("").filter(function (ch) {
            const c = ch.charCodeAt(0);
            return (c >= 32 || c === 9 || c === 10 || c === 13) && c !== 0xFFFE && c !== 0xFFFF;
        }).join("")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function relations(liste) {
    return XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + liste.map(r => '<Relationship Id="' + r[0] + '" Type="' + r[1] + '" Target="' + r[2] + '"/>').join("")
        + "</Relationships>";
}

function xfrm(x, y, l, h) {
    return '<a:xfrm><a:off x="' + Math.round(x) + '" y="' + Math.round(y) + '"/>'
        + '<a:ext cx="' + Math.round(l) + '" cy="' + Math.round(h) + '"/></a:xfrm>';
}

function arbreFormes(formes) {
    return '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        + '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        + '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        + formes.join("") + "</p:spTree></p:cSld>";
}

/* paragraphes : [{ texte, taille (centièmes de point), gras, couleur, align }] */
function zoneTexte(id, nom, x, y, l, h, paragraphes, ancre) {
    const ps = paragraphes.map(p =>
        "<a:p>" + (p.align ? '<a:pPr algn="' + p.align + '"/>' : "")
        + '<a:r><a:rPr lang="fr-CA" sz="' + p.taille + '"' + (p.gras ? ' b="1"' : "") + ' dirty="0">'
        + '<a:solidFill><a:srgbClr val="' + p.couleur + '"/></a:solidFill></a:rPr>'
        + "<a:t>" + echapperXml(p.texte) + "</a:t></a:r></a:p>").join("");
    return '<p:sp><p:nvSpPr><p:cNvPr id="' + id + '" name="' + nom + '"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        + "<p:spPr>" + xfrm(x, y, l, h) + '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        + '<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="' + (ancre || "t") + '">'
        + "<a:normAutofit/></a:bodyPr><a:lstStyle/>" + ps + "</p:txBody></p:sp>";
}

function formeImage(id, rid, x, y, l, h) {
    return '<p:pic><p:nvPicPr><p:cNvPr id="' + id + '" name="Graphique"/>'
        + '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        + '<p:blipFill><a:blip r:embed="' + rid + '"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        + "<p:spPr>" + xfrm(x, y, l, h) + '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>';
}

function diapositive(formes) {
    return XML_DECL + "<p:sld" + NS_PPT + ">" + arbreFormes(formes)
        + "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>";
}

/* Le titre au fil des filtres peut être long : on réduit le corps plutôt
   que de laisser le texte déborder sur l'image. normAutofit ne s'applique
   qu'à la première retouche dans PowerPoint, d'où ce calcul préalable. */
function tailleTitre(texte) {
    const n = texte.length;
    return n > 140 ? 1400 : n > 100 ? 1700 : n > 60 ? 2000 : 2400;
}

function themeXml() {
    const plein = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>';
    const trait = '<a:ln w="6350">' + plein + "</a:ln>";
    const effet = "<a:effectStyle><a:effectLst/></a:effectStyle>";
    const couleur = (nom, val) => "<a:" + nom + '><a:srgbClr val="' + val + '"/></a:' + nom + ">";
    const police = '<a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/>';
    return XML_DECL + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Rapport">'
        + '<a:themeElements><a:clrScheme name="Rapport">'
        + couleur("dk1", "000000") + couleur("lt1", "FFFFFF") + couleur("dk2", "1F2937") + couleur("lt2", "F5F5F5")
        + couleur("accent1", "2563EB") + couleur("accent2", "DC2626") + couleur("accent3", "16A34A")
        + couleur("accent4", "D97706") + couleur("accent5", "7C3AED") + couleur("accent6", "0891B2")
        + couleur("hlink", "2563EB") + couleur("folHlink", "7C3AED")
        + '</a:clrScheme><a:fontScheme name="Rapport"><a:majorFont>' + police + "</a:majorFont>"
        + "<a:minorFont>" + police + "</a:minorFont></a:fontScheme>"
        + '<a:fmtScheme name="Rapport">'
        + "<a:fillStyleLst>" + plein + plein + plein + "</a:fillStyleLst>"
        + "<a:lnStyleLst>" + trait + trait + trait + "</a:lnStyleLst>"
        + "<a:effectStyleLst>" + effet + effet + effet + "</a:effectStyleLst>"
        + "<a:bgFillStyleLst>" + plein + plein + plein + "</a:bgFillStyleLst>"
        + "</a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>";
}

/* doc : { titrePage, sousTitre, diapos: [{ titre, sousTitre, filtres, png, largeur, hauteur }] }
   largeur/hauteur : dimensions de l'image, dans n'importe quelle unité —
   seul leur rapport compte. Retourne un Blob .pptx. */
function construirePptx(doc) {
    const n = doc.diapos.length + 1;   // + la page couverture
    const fichiers = [];
    const ajouter = (nom, octets) => fichiers.push({ nom: nom, octets: octets });

    let types = XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        + '<Default Extension="xml" ContentType="application/xml"/>'
        + '<Default Extension="png" ContentType="image/png"/>'
        + '<Override PartName="/ppt/presentation.xml" ContentType="' + CT_PML + 'presentation.main+xml"/>'
        + '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="' + CT_PML + 'slideMaster+xml"/>'
        + '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="' + CT_PML + 'slideLayout+xml"/>'
        + '<Override PartName="/ppt/presProps.xml" ContentType="' + CT_PML + 'presProps+xml"/>'
        + '<Override PartName="/ppt/viewProps.xml" ContentType="' + CT_PML + 'viewProps+xml"/>'
        + '<Override PartName="/ppt/tableStyles.xml" ContentType="' + CT_PML + 'tableStyles+xml"/>'
        + '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        + '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>';
    for (let i = 1; i <= n; i++) {
        types += '<Override PartName="/ppt/slides/slide' + i + '.xml" ContentType="' + CT_PML + 'slide+xml"/>';
    }
    ajouter("[Content_Types].xml", types + "</Types>");

    ajouter("_rels/.rels", relations([
        ["rId1", REL + "officeDocument", "ppt/presentation.xml"],
        ["rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"],
        ["rId3", REL + "extended-properties", "docProps/app.xml"],
    ]));

    const maintenant = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
    ajouter("docProps/core.xml", XML_DECL
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        + ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
        + ' xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + "<dc:title>" + echapperXml(doc.titrePage) + "</dc:title>"
        + '<dcterms:created xsi:type="dcterms:W3CDTF">' + maintenant + "</dcterms:created>"
        + '<dcterms:modified xsi:type="dcterms:W3CDTF">' + maintenant + "</dcterms:modified>"
        + "</cp:coreProperties>");
    ajouter("docProps/app.xml", XML_DECL
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        + ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        + "<Application>Microsoft Office PowerPoint</Application><Slides>" + n + "</Slides></Properties>");

    let idsDiapos = "";
    const relsPres = [["rId1", REL + "slideMaster", "slideMasters/slideMaster1.xml"]];
    for (let i = 1; i <= n; i++) {
        idsDiapos += '<p:sldId id="' + (255 + i) + '" r:id="rId' + (i + 1) + '"/>';
        relsPres.push(["rId" + (i + 1), REL + "slide", "slides/slide" + i + ".xml"]);
    }
    relsPres.push(["rId" + (n + 2), REL + "presProps", "presProps.xml"]);
    relsPres.push(["rId" + (n + 3), REL + "viewProps", "viewProps.xml"]);
    relsPres.push(["rId" + (n + 4), REL + "theme", "theme/theme1.xml"]);
    relsPres.push(["rId" + (n + 5), REL + "tableStyles", "tableStyles.xml"]);
    ajouter("ppt/presentation.xml", XML_DECL + "<p:presentation" + NS_PPT + ' saveSubsetFonts="1">'
        + '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        + "<p:sldIdLst>" + idsDiapos + "</p:sldIdLst>"
        + '<p:sldSz cx="' + EMU_L + '" cy="' + EMU_H + '"/><p:notesSz cx="6858000" cy="9144000"/>'
        + "</p:presentation>");
    ajouter("ppt/_rels/presentation.xml.rels", relations(relsPres));
    ajouter("ppt/presProps.xml", XML_DECL + "<p:presentationPr" + NS_PPT + "/>");
    ajouter("ppt/viewProps.xml", XML_DECL + "<p:viewPr" + NS_PPT + "/>");
    ajouter("ppt/tableStyles.xml", XML_DECL
        + '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        + ' def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>');
    ajouter("ppt/theme/theme1.xml", themeXml());

    ajouter("ppt/slideMasters/slideMaster1.xml", XML_DECL + "<p:sldMaster" + NS_PPT + ">"
        + '<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
        + arbreFormes([]).slice("<p:cSld>".length)
        + '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2"'
        + ' accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6"'
        + ' hlink="hlink" folHlink="folHlink"/>'
        + '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        + "<p:txStyles>"
        + '<p:titleStyle><a:lvl1pPr><a:defRPr sz="3200"/></a:lvl1pPr></p:titleStyle>'
        + '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:bodyStyle>'
        + '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle>'
        + "</p:txStyles></p:sldMaster>");
    ajouter("ppt/slideMasters/_rels/slideMaster1.xml.rels", relations([
        ["rId1", REL + "slideLayout", "../slideLayouts/slideLayout1.xml"],
        ["rId2", REL + "theme", "../theme/theme1.xml"],
    ]));
    ajouter("ppt/slideLayouts/slideLayout1.xml", XML_DECL
        + "<p:sldLayout" + NS_PPT + ' type="blank" preserve="1">'
        + arbreFormes([]).replace("<p:cSld>", '<p:cSld name="Vide">')
        + "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>");
    ajouter("ppt/slideLayouts/_rels/slideLayout1.xml.rels", relations([
        ["rId1", REL + "slideMaster", "../slideMasters/slideMaster1.xml"],
    ]));
    const relLayout = ["rId1", REL + "slideLayout", "../slideLayouts/slideLayout1.xml"];

    const largeurUtile = EMU_L - 2 * EMU_MARGE;
    ajouter("ppt/slides/slide1.xml", diapositive([
        zoneTexte(2, "Titre", EMU_MARGE, 2286000, largeurUtile, 1371600,
                  [{ texte: doc.titrePage, taille: 3600, gras: true, couleur: "0B0B0B", align: "ctr" }], "b"),
        zoneTexte(3, "Sous-titre", EMU_MARGE, 3794760, largeurUtile, 914400,
                  [{ texte: doc.sousTitre, taille: 1800, couleur: "52514E", align: "ctr" }]),
    ]));
    ajouter("ppt/slides/_rels/slide1.xml.rels", relations([relLayout]));

    const H_TITRE = 914400;
    const H_SOUS_TITRE = 502920;
    const H_PIED = 548640;
    const ESPACE = 91440;
    const piedY = EMU_H - EMU_MARGE - H_PIED;
    doc.diapos.forEach(function (d, i) {
        const num = i + 2;
        /* Le sous-titre (titre au fil des filtres) s'intercale sous le titre
           de section, comme dans le rapport; l'image cède la place. */
        const hEntete = H_TITRE + (d.sousTitre ? H_SOUS_TITRE : 0);
        const zoneY = EMU_MARGE + hEntete + ESPACE;
        const zoneH = piedY - ESPACE - zoneY;
        const echelle = Math.min(largeurUtile / d.largeur, zoneH / d.hauteur);
        const l = d.largeur * echelle;
        const h = d.hauteur * echelle;
        const formes = [
            zoneTexte(2, "Titre", EMU_MARGE, EMU_MARGE, largeurUtile, H_TITRE,
                      [{ texte: d.titre, taille: tailleTitre(d.titre), gras: true, couleur: "0B0B0B" }], "b"),
            formeImage(3, "rId2", EMU_MARGE + (largeurUtile - l) / 2, zoneY + (zoneH - h) / 2, l, h),
        ];
        if (d.sousTitre) {
            const n = d.sousTitre.length;
            formes.push(zoneTexte(5, "Sous-titre", EMU_MARGE, EMU_MARGE + H_TITRE, largeurUtile, H_SOUS_TITRE,
                                  [{ texte: d.sousTitre, taille: n > 150 ? 1100 : n > 100 ? 1300 : 1600,
                                     couleur: "52514E" }]));
        }
        if (d.filtres) {
            formes.push(zoneTexte(4, "Filtres", EMU_MARGE, piedY, largeurUtile, H_PIED,
                                  [{ texte: d.filtres, taille: 1000, couleur: "52514E" }]));
        }
        ajouter("ppt/slides/slide" + num + ".xml", diapositive(formes));
        ajouter("ppt/slides/_rels/slide" + num + ".xml.rels", relations([
            relLayout,
            ["rId2", REL + "image", "../media/image" + (i + 1) + ".png"],
        ]));
        ajouter("ppt/media/image" + (i + 1) + ".png", d.png);
    });

    return zipStore(fichiers, CT_PML + "presentation");
}

/* ================= Export PowerPoint : filtres et choix =================
   Même posture que legende() : tout est lu dans le DOM, rien dans les
   données. Chaque diapositive reprend l'image du bouton « ↓ PNG » (sans
   son en-tête, le titre devenant du texte modifiable) et, en pied, les
   filtres en vigueur pour ce graphique. */

function propre(texte) {
    return (texte || "").trim().replace(/\s+/g, " ");
}

/* Barres de filtres qui gouvernent un graphique : celle, épinglée, de son
   groupe (.chart-group) — ou, hors groupe (épreuves, classe),
   toute barre épinglée visible hors groupe —, plus les menus posés dans sa
   propre section (Cours, Année, Résultat…).

   Une barre hors groupe qui porte data-export-panneaux (liste d'id de
   panneaux, séparés par des espaces) ne vaut que pour ces panneaux : le
   rapport « Projet éducatif » en a une par panneau, et sans cela la barre
   Matière/Compétence du parcours de cohorte se retrouvait au pied des
   diapositives des objectifs du projet éducatif. */
function barresDe(cible) {
    const barres = [];
    const groupe = cible.closest(".chart-group");
    if (groupe) {
        barres.push.apply(barres, Array.from(groupe.querySelectorAll(":scope > .global-filters-sticky")));
    } else {
        const panneau = cible.closest("details.panel");
        for (const b of Array.from(document.querySelectorAll(".global-filters-sticky"))) {
            if (b.closest(".chart-group") || !b.getClientRects().length) continue;
            const pour = b.dataset.exportPanneaux;
            if (pour && !(panneau && pour.split(/\s+/).includes(panneau.id))) continue;
            barres.push(b);
        }
    }
    const corps = cible.closest(".panel-body");
    if (corps) barres.push.apply(barres, Array.from(corps.querySelectorAll(".global-filters-menu")));
    return barres;
}

/* Sélecteurs « :scope > » : les listes déroulantes des sélecteurs d'école
   contiennent leurs propres cases et libellés, qu'il ne faut pas lire. */
function lireFiltre(item) {
    const caseACocher = item.querySelector(":scope > input[type=checkbox]");
    if (caseACocher) {
        const lib = item.querySelector(":scope > span, :scope > label");
        const libelle = lib ? propre(lib.textContent) : "";
        return libelle ? { libelle: libelle, valeur: caseACocher.checked ? "oui" : "non" } : null;
    }
    const etiquette = item.querySelector(":scope > label");
    const libelle = etiquette ? propre(etiquette.textContent) : "";
    let valeur = "";
    const liste = item.querySelector(":scope > select");
    const bascule = item.querySelector(":scope > .chart-type-toggle .chart-type-btn.active");
    const selecteur = item.querySelector(":scope > .school-picker-btn");
    if (liste) valeur = Array.from(liste.selectedOptions).map(o => propre(o.text)).join(", ");
    else if (bascule) valeur = propre(bascule.textContent);
    else if (selecteur) valeur = propre(selecteur.textContent);
    if (/^Sélectionner/.test(valeur)) valeur = "aucun";
    return libelle && valeur ? { libelle: libelle, valeur: valeur } : null;
}

function filtresDe(cible) {
    const vus = new Set();
    const out = [];
    for (const barre of barresDe(cible)) {
        for (const item of Array.from(barre.querySelectorAll(".global-filter-item"))) {
            if (vus.has(item) || !item.getClientRects().length) continue;
            vus.add(item);
            const f = lireFiltre(item);
            if (f) out.push(f);
        }
    }
    return out;
}

/* Tous les graphiques de la page, un poste par DIAPOSITIVE : les
   sous-graphiques d'une même rangée (.subplot-row) comptent pour un seul,
   puisqu'ils partiront sur une même image (voir composerGroupe).

   Un graphique masqué par le mode de page (sections de l'autre mode) n'est
   pas listé; un graphique d'une section repliée ou sans donnée l'est, mais
   désactivé : il n'y a rien à copier. */
function recenserGraphiques() {
    const rangees = new Map();
    const out = [];
    for (const cible of Array.from(document.querySelectorAll(CIBLES))) {
        const replie = cible.closest("details:not([open])");
        if (replie ? !replie.getClientRects().length : !cible.getClientRects().length) continue;
        const trace = !replie && !estVide(cible)
            && Array.from(cible.querySelectorAll("canvas, svg")).some(estVisible);
        const rangee = cible.closest(".subplot-row");
        const deja = rangee ? rangees.get(rangee) : null;
        if (deja) {
            deja.cibles.push(cible);
            deja.exportable = deja.exportable || trace;
            continue;
        }
        const t = titres(cible, { sousTitre: !rangee });
        const poste = {
            cibles: [cible],
            titre: !t.section ? t.titre
                   : t.fil && t.fil !== t.section ? t.section + " — " + t.fil : t.section,
            exportable: trace,
        };
        if (rangee) rangees.set(rangee, poste);
        out.push(poste);
    }
    return out;
}

function titrePage() {
    const h1 = document.querySelector("h1");
    return propre(document.title) || (h1 ? propre(h1.textContent) : "") || "Rapport";
}

/* lots : une entrée par diapositive — un élément CIBLES, ou un tableau
   d'éléments d'une même rangée, réunis sur une seule image. Par défaut :
   tout ce qui est tracé, groupé comme dans la boîte de choix.
   progression(n, total) est appelé avant chaque diapositive. Retourne le
   Blob téléchargé, ou null s'il n'y avait rien à exporter. */
async function exporterPowerPoint(lots, progression) {
    if (!lots) lots = recenserGraphiques().filter(g => g.exportable).map(g => g.cibles);
    lots = lots.map(l => (Array.isArray(l) ? l : [l]));
    const diapos = [];
    for (let i = 0; i < lots.length; i++) {
        if (progression) progression(i + 1, lots.length);
        const lot = lots[i];
        const image = lot.length > 1 ? await composerGroupe(lot)
                                     : await composer(lot[0], { entete: false });
        if (!image) continue;
        const blob = await enBlob(image.canvas);
        if (!blob) continue;
        /* Section en titre, titre au fil des filtres en sous-titre — sauf
           s'il répète la section (graphique sans titre au fil des filtres). */
        const t = image.titres;
        diapos.push({
            titre: t.section || image.titre,
            sousTitre: t.section && t.fil !== t.section ? t.fil : "",
            filtres: filtresDe(lot[0]).map(f => f.libelle + " : " + f.valeur).join("  ·  "),
            png: new Uint8Array(await blob.arrayBuffer()),
            largeur: image.largeur,
            hauteur: image.hauteur,
        });
    }
    if (!diapos.length) return null;

    const d = new Date();
    const p = x => String(x).padStart(2, "0");
    const quand = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
                  + " à " + p(d.getHours()) + ":" + p(d.getMinutes());
    const titre = titrePage();
    const pptx = construirePptx({
        titrePage: titre,
        sousTitre: "Généré le " + quand + " — " + diapos.length
                   + (diapos.length > 1 ? " graphiques" : " graphique"),
        diapos: diapos,
    });
    telecharger(pptx, nomFichier(titre, ".pptx"));
    return pptx;
}

function creerBouton(texte, classe) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = texte;
    if (classe) b.className = classe;
    return b;
}

function ouvrirDialoguePptx(declencheur) {
    const graphiques = recenserGraphiques();
    const dialogue = document.createElement("dialog");
    dialogue.className = "export-pptx-dialog";

    const entete = document.createElement("h2");
    entete.textContent = "Exporter en PowerPoint";
    const aide = document.createElement("p");
    aide.className = "export-pptx-aide";
    aide.textContent = "Une diapositive par graphique coché, tel qu'il est affiché, "
                       + "avec les filtres en vigueur en pied de page.";

    const liste = document.createElement("div");
    liste.className = "export-pptx-liste";
    const cases = [];
    for (const g of graphiques) {
        const ligne = document.createElement("label");
        ligne.className = "export-pptx-ligne" + (g.exportable ? "" : " inactif");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = g.exportable;
        cb.disabled = !g.exportable;
        const texte = document.createElement("span");
        texte.textContent = g.titre
            + (g.cibles.length > 1 ? " (" + g.cibles.length + " sous-graphiques réunis)" : "")
            + (g.exportable ? "" : " (vide ou section repliée)");
        ligne.append(cb, texte);
        liste.appendChild(ligne);
        cases.push({ cb: cb, g: g });
    }
    if (!graphiques.length) liste.textContent = "Aucun graphique sur cette page.";

    const pied = document.createElement("div");
    pied.className = "export-pptx-pied";
    const tout = creerBouton("Tout cocher");
    const aucun = creerBouton("Tout décocher");
    const etat = document.createElement("span");
    etat.className = "export-pptx-etat";
    const annuler = creerBouton("Annuler");
    const valider = creerBouton("Télécharger", "principal");
    pied.append(tout, aucun, etat, annuler, valider);

    function majValider() { valider.disabled = !cases.some(c => c.cb.checked); }
    function cocher(valeur) {
        for (const c of cases) if (!c.cb.disabled) c.cb.checked = valeur;
        majValider();
    }
    liste.addEventListener("change", majValider);
    tout.addEventListener("click", () => cocher(true));
    aucun.addEventListener("click", () => cocher(false));
    annuler.addEventListener("click", () => dialogue.close());
    valider.addEventListener("click", function () {
        const choisis = cases.filter(c => c.cb.checked).map(c => c.g.cibles);
        valider.disabled = true;
        etat.textContent = "Préparation…";
        exporterPowerPoint(choisis, (n, total) => { etat.textContent = "Graphique " + n + " / " + total + "…"; })
            .then(function (blob) {
                dialogue.close();
                if (!blob) clignote(declencheur, "vide");
            })
            .catch(function (err) {
                console.error(err);
                etat.textContent = "Échec de l'export.";
                majValider();
            });
    });
    dialogue.addEventListener("close", () => dialogue.remove());

    dialogue.append(entete, aide, liste, pied);
    document.body.appendChild(dialogue);
    majValider();
    dialogue.showModal();
}

function installerBoutonPptx() {
    if (document.querySelector(".export-pptx-btn") || !document.querySelector(CIBLES)) return;
    const bouton = creerBouton("", "export-pptx-btn");
    bouton.dataset.libelle = "↓ PowerPoint";
    bouton.textContent = bouton.dataset.libelle;
    bouton.title = "Exporter les graphiques choisis dans une présentation PowerPoint, tels qu'ils sont affichés";
    bouton.addEventListener("click", () => ouvrirDialoguePptx(bouton));
    document.body.appendChild(bouton);
}

installer();
/* Exposés pour un graphique ajouté au DOM après coup : re-poser les boutons
   est sans effet sur ceux qui existent déjà. */
window.installerExportGraphiques = installer;
window.exporterPowerPoint = exporterPowerPoint;
})();

(function () {
    const CODES = new Set([17, 21]);
    const TEXTE = "Les données antérieures à 2025-2026 de cette école ont été réparties rétroactivement entre les écoles 021 et 017, à partir de l'inscription des élèves en 2025 ou de leur code postal.";
    for (const id of ["f-ecole", "f-h-ecole", "c-ecole"]) {
        const select = document.getElementById(id);
        if (!select) continue;
        const note = document.createElement("div");
        note.textContent = TEXTE;
        note.style.cssText = "font-size:0.8em;opacity:0.75;margin-top:4px;max-width:32em;";
        select.insertAdjacentElement("afterend", note);
        const maj = () => { note.style.display = CODES.has(Number(select.value)) ? "" : "none"; };
        select.addEventListener("change", maj);
        maj();
    }
})();
