/* LaZoo 0.55: logotipo animado (sin librerías).
   <span class="lz-logo" data-estado="desconectado"></span> dibuja «LaZoo» en SVG. La última «o»
   es un anillo rojo; al conectar, las dos «o» se funden en el infinito verde (~1 s). Al
   desconectar hace lo contrario. «esperando» = anillo naranja que late suave.
   El estado sale solo del atributo data-link="on|off" de la cabecera (.top) más cercana, así que
   no hace falta tocar la lógica de conexión. Con prefers-reduced-motion cambia sin animación.
   Geometría: la misma que diseno/logos.py (los SVG de static/img salen de ahí). */
(function () {
  "use strict";
  // <letras> generado por diseno/logos.py: L, a, Z de Poppins Bold (OFL) en trazos.
  var LETRAS = "M93.9 386.8H140.9V414.5H58.0V267.1H93.9ZM213.6 295.7Q226.0 295.7 235.4 300.7Q244.7 305.8 249.8 313.9V297.4H285.6V414.5H249.8V397.9Q244.5 406.1 235.2 411.1Q225.8 416.2 213.4 416.2Q199.2 416.2 187.4 408.7Q175.6 401.3 168.8 387.5Q162.0 373.8 162.0 355.7Q162.0 337.7 168.8 324.0Q175.6 310.4 187.4 303.0Q199.2 295.7 213.6 295.7ZM224.1 327.0Q213.4 327.0 206.0 334.6Q198.5 342.3 198.5 355.7Q198.5 369.2 206.0 377.0Q213.4 384.9 224.1 384.9Q234.8 384.9 242.3 377.1Q249.8 369.4 249.8 355.9Q249.8 342.5 242.3 334.7Q234.8 327.0 224.1 327.0ZM314.7 385.1H378.1V414.5H274.0V387.2L337.0 296.5H274.0V267.1H378.1V294.4Z";
  // </letras>
  var ROJO = [232, 16, 28], VERDE = [26, 143, 58], BLANCO = [255, 255, 255], NARANJA = [224, 122, 61];
  var R = 41.5, TRAZO = 27.5, O1 = 439.5, O2 = 556, CY = 358.5, IC = 505.5, A = 105, SY = 1.25, N = 48;
  var DURACION = 1050;
  var NS = "http://www.w3.org/2000/svg";

  function bucles(p) {
    var out = [];
    [[O1, Math.PI / 2, -1], [O2, -Math.PI / 2, 1]].forEach(function (b) {
      var d = "";
      for (var i = 0; i < N; i++) {
        var t = b[1] + (Math.PI * i) / N;
        var th = b[2] < 0 ? Math.PI - 2 * t : 2 * t; // mismo sentido que el lóbulo
        var ax = b[0] + R * Math.cos(th), ay = CY + R * Math.sin(th);
        var s = Math.sin(t), c = Math.cos(t), q = 1 + s * s;
        var bx = IC + (A * c) / q, by = CY + (SY * A * s * c) / q;
        d += (i ? "L" : "M") + (ax + (bx - ax) * p).toFixed(2) + " " + (ay + (by - ay) * p).toFixed(2);
      }
      out.push(d + "Z");
    });
    return out;
  }

  function mezcla(a, b, p) {
    return "rgb(" + a.map(function (v, i) { return Math.round(v + (b[i] - v) * p); }).join(",") + ")";
  }

  // Suave al empezar y al acabar, con un pequeño rebote final para que «encaje».
  function curva(x) {
    var e = x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    return e + Math.sin(Math.PI * x) * 0.06 * x;
  }

  // Rojo/naranja a verde pasando por el tono (naranja, amarillo), no por un marrón apagado.
  function hsl(rgb) {
    var r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn, h = 0, s = 0;
    if (d) {
      s = d / (1 - Math.abs(2 * l - 1));
      h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h = (h * 60 + 360) % 360;
    }
    return [h, s, l];
  }
  function mezclaTono(a, b, p) {
    var x = hsl(a), y = hsl(b);
    var dh = y[0] - x[0];
    if (dh < 0) dh += 360; // de rojo (0°) a verde (137°) subiendo por naranja y amarillo
    return "hsl(" + ((x[0] + dh * p) % 360).toFixed(1) + "," + ((x[1] + (y[1] - x[1]) * p) * 100).toFixed(1) + "%," + ((x[2] + (y[2] - x[2]) * p) * 100).toFixed(1) + "%)";
  }

  function sinMovimiento() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function Logo(el) {
    this.el = el;
    this.p = 0; // 0 = anillo, 1 = infinito
    this.raf = 0;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "50 258 584 166");
    svg.setAttribute("class", "lz-logo-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "LaZoo");
    var letras = document.createElementNS(NS, "path");
    letras.setAttribute("d", LETRAS);
    letras.setAttribute("fill", "#fff");
    svg.appendChild(letras);
    this.o = [0, 1].map(function () {
      var p = document.createElementNS(NS, "path");
      p.setAttribute("fill", "none");
      p.setAttribute("stroke-width", TRAZO);
      p.setAttribute("stroke-linejoin", "round");
      p.setAttribute("class", "lz-o");
      svg.appendChild(p);
      return p;
    });
    el.textContent = "";
    el.appendChild(svg);
    this.estado = null;
    this.poner(el.getAttribute("data-estado") || "desconectado", true);
  }

  Logo.prototype.dibujar = function (p) {
    this.p = p;
    var d = bucles(Math.max(-0.05, Math.min(1.05, p)));
    var k = Math.max(0, Math.min(1, p));
    var final = this.estado === "esperando" ? NARANJA : ROJO;
    this.o[0].setAttribute("d", d[0]);
    this.o[1].setAttribute("d", d[1]);
    this.o[0].setAttribute("stroke", mezcla(BLANCO, VERDE, k));
    this.o[1].setAttribute("stroke", mezclaTono(final, VERDE, k));
  };

  Logo.prototype.poner = function (estado, ya) {
    if (estado === this.estado) return;
    this.estado = estado;
    this.el.setAttribute("data-estado", estado);
    var meta = estado === "conectado" ? 1 : 0;
    window.cancelAnimationFrame(this.raf);
    if (ya || sinMovimiento() || this.p === meta) {
      this.dibujar(meta);
      return;
    }
    var self = this, desde = this.p, t0 = 0;
    function paso(ts) {
      if (!t0) t0 = ts;
      var x = Math.min(1, (ts - t0) / DURACION);
      self.dibujar(desde + (meta - desde) * curva(x));
      if (x < 1) self.raf = window.requestAnimationFrame(paso);
      else self.dibujar(meta);
    }
    this.raf = window.requestAnimationFrame(paso);
  };

  // Estado según la cabecera: data-link on/off y, en el móvil, el aviso de espera visible.
  function estadoDe(el) {
    var top = el.closest("[data-link]");
    if (top && top.getAttribute("data-link") === "on") return "conectado";
    var aviso = document.getElementById("wait-banner");
    if (aviso && !aviso.hidden) return "esperando";
    return "desconectado";
  }

  // Favicon coherente con el estado (rojo / verde) en las páginas que lo piden.
  function favicon(estado) {
    var link = document.querySelector("link[rel=icon][data-dinamico]");
    if (!link) return;
    var href = estado === "conectado" ? "/img/infinito-verde.svg" : "/img/infinito-rojo.svg";
    if (link.getAttribute("href") !== href) link.setAttribute("href", href);
  }

  function iniciar() {
    var logos = Array.prototype.map.call(document.querySelectorAll(".lz-logo"), function (el) {
      var l = new Logo(el);
      l.poner(estadoDe(el), true);
      return l;
    });
    function revisar() {
      logos.forEach(function (l) {
        var e = estadoDe(l.el);
        l.poner(e);
        favicon(e);
      });
    }
    revisar();
    var obs = new MutationObserver(revisar);
    document.querySelectorAll("[data-link], #wait-banner").forEach(function (n) {
      obs.observe(n, { attributes: true, attributeFilter: ["data-link", "hidden"] });
    });
    window.LaZooLogo = { logos: logos, revisar: revisar, bucles: bucles };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
