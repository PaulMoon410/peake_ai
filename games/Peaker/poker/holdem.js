/* Texas Hold'em Front-End Logic (offline, no betting yet) */
(function(){
  const suits = ['♠','♥','♦','♣'];
  const ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A'];
  const RANK_VALUE = Object.fromEntries(ranks.map((r,i)=>[r,i])); // 0..12
  let deck = [], player = [], dealer = [], community = []; // arrays of card objects
  let phase = 'idle'; // idle, preflop, flop, turn, river, showdown
  let inProgress = false;
  const dealBtn = document.getElementById('dealBtn');
  const nextBtn = document.getElementById('nextBtn');
  const foldBtn = document.getElementById('foldBtn');
  const newBtn = document.getElementById('newGameBtn');
  const statusEl = document.getElementById('gameStatus');

  function buildDeck(){
    const d=[]; suits.forEach(s=>ranks.forEach(r=>d.push({rank:r,suit:s,color:(s==='♥'||s==='♦')?'red':'black'})));
    for(let i=d.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1)); [d[i],d[j]]=[d[j],d[i]];} return d;
  }
  function popCard(){ return deck.pop(); }

  function startHand(){
    deck = buildDeck(); player=[]; dealer=[]; community=[]; phase='preflop'; inProgress=true;
    // deal hole cards
    player.push(popCard(), popCard());
    dealer.push(popCard(), popCard());
    renderAll();
    updateStatus('Cards dealt. Click Next for the Flop.');
    dealBtn.disabled = true; nextBtn.disabled = false; foldBtn.disabled = false; newBtn.disabled = true;
  }

  function advance(){
    if(!inProgress) return;
    if(phase==='preflop'){ community.push(popCard(),popCard(),popCard()); phase='flop'; updateStatus('Flop revealed. Next for Turn.'); }
    else if(phase==='flop'){ community.push(popCard()); phase='turn'; updateStatus('Turn revealed. Next for River.'); }
    else if(phase==='turn'){ community.push(popCard()); phase='river'; updateStatus('River revealed. Next for Showdown.'); }
    else if(phase==='river'){ phase='showdown'; showdown(); return; }
    renderAll();
  }

  function fold(){ if(!inProgress) return; phase='showdown'; inProgress=false; revealDealer(); updateStatus('You folded. Dealer wins.'); endControls(); }

  function showdown(){
    revealDealer();
    const pRes = bestHoldemHand(player.concat(community));
    const dRes = bestHoldemHand(dealer.concat(community));
    highlightBest('playerCards', pRes.best); highlightBest('dealerCards', dRes.best);
    const cmp = compareHandResults(pRes, dRes);
    let msg = `Your ${pRes.name} vs Dealer ${dRes.name}. `;
    if(cmp>0){ msg += 'You win!'; stats.wins++; }
    else if(cmp<0){ msg += 'Dealer wins.'; stats.losses++; }
    else { msg+='Tie!'; stats.ties++; }
    stats.hands++; updateStatsDisplay();
    updateStatus(msg); inProgress=false; endControls(); renderAll();
  }

  function endControls(){ nextBtn.disabled=true; foldBtn.disabled=true; newBtn.disabled=false; }
  function newHand(){ phase='idle'; inProgress=false; player=[]; dealer=[]; community=[]; clearHighlights(); renderAll(); updateStatus('Ready. Deal a new hand.'); dealBtn.disabled=false; nextBtn.disabled=true; foldBtn.disabled=true; newBtn.disabled=true; }

  function renderAll(){
    // Player cards should always be face-up once dealt
    renderCards('playerCards', player, true);
    // Dealer cards stay hidden until showdown
    renderCards('dealerCards', dealer, phase==='showdown');
    renderCommunity();
    updateStrengths();
    updatePhaseLabel();
  }
  function updateStrengths(){
    const handStrengthEl = document.getElementById('handStrength');
    const dealerStrengthEl = document.getElementById('dealerStrength');
    if(player.length){
      const known = player.concat(community);
      if(known.length>=5){
        const res = bestHoldemHand(known);
        handStrengthEl.textContent = 'Hand: '+res.name;
      } else {
        handStrengthEl.textContent = 'Hand: Waiting...';
      }
    }
    if(phase==='showdown'){
      const dKnown = dealer.concat(community);
      const dRes = bestHoldemHand(dKnown);
      dealerStrengthEl.textContent = 'Hand: '+dRes.name;
    } else {
      dealerStrengthEl.textContent = 'Hand: Hidden';
    }
  }
  function renderCards(id, cards, show){
    const el=document.getElementById(id); el.innerHTML='';
    cards.forEach(c=>{
      const d=document.createElement('div');
      d.className='card '+(show?c.color:'hidden');
      d.textContent= show? (c.rank+c.suit): '?';
      el.appendChild(d);
    });
  }
  function renderCommunity(){ const el=document.getElementById('communityCards'); el.innerHTML=''; community.forEach(c=>{ const d=document.createElement('div'); d.className='card '+c.color; d.textContent=c.rank+c.suit; el.appendChild(d); }); }
  function revealDealer(){ renderCards('dealerCards', dealer, true); }
  function updateStatus(msg){ statusEl.textContent = msg; statusEl.setAttribute('aria-live','polite'); }
  function updatePhaseLabel(){
    const phaseNames={idle:'Idle',preflop:'Pre-Flop',flop:'Flop',turn:'Turn',river:'River',showdown:'Showdown'};
    document.getElementById('currentPhase').textContent='Phase: '+phaseNames[phase];
    updateProgress();
  }
  function updateProgress(){
    const order=['preflop','flop','turn','river','showdown'];
    const idx = order.indexOf(phase);
    const steps = document.querySelectorAll('#phaseProgress .step');
    steps.forEach((el,i)=>{ el.classList.toggle('active', i<=idx && idx!==-1); });
  }

  // Hand evaluation utilities
  function bestHoldemHand(seven){ // choose best 5 of 7
    const combos = kCombinations(seven,5);
    let best=null; combos.forEach(set=>{ const evalRes = evaluateFive(set); if(!best || compareEval(evalRes,best)>0) best=evalRes; });
    return best; // {rank, name, scoreArray, best:Set}
  }
  function kCombinations(arr,k){ const res=[]; (function rec(start,combo){ if(combo.length===k){ res.push(combo.slice()); return;} for(let i=start;i<arr.length;i++){ combo.push(arr[i]); rec(i+1,combo); combo.pop(); } })(0,[]); return res; }

  function evaluateFive(cards){ // returns rank strength, and ordered tie breakers
    const ranksSorted = cards.map(c=>RANK_VALUE[c.rank]).sort((a,b)=>b-a);
    const counts = {}; cards.forEach(c=>{ const v=RANK_VALUE[c.rank]; counts[v]=(counts[v]||0)+1; });
    const suitCounts = {}; cards.forEach(c=>{ suitCounts[c.suit]=(suitCounts[c.suit]||0)+1; });
    const isFlush = Object.values(suitCounts).some(v=>v===5);
    const uniqRanks = [...new Set(ranksSorted)];
    const isStraight = uniqRanks.length===5 && (uniqRanks[0]-uniqRanks[4]===4 || // normal
      // wheel A-2-3-4-5
      JSON.stringify(uniqRanks.slice().sort((a,b)=>a-b))===JSON.stringify([0,1,2,3,12]));
    let highStraight = null; if(isStraight){ highStraight = ranksSorted.includes(12)&&ranksSorted.includes(3)&&ranksSorted.includes(0)?3:uniqRanks[0]; }
    // Build pattern arrays for tie break
    // Count groups
    const groups = Object.entries(counts).map(([v,c])=>({v:parseInt(v),c})).sort((a,b)=>{ if(b.c!==a.c) return b.c-a.c; return b.v-a.v; });
    let rankCategory, name, scoreArr;
    if(isStraight && isFlush){ rankCategory=8; name='Straight Flush'; scoreArr=[highStraight]; }
    else if(groups[0].c===4){ rankCategory=7; name='Four of a Kind'; scoreArr=[groups[0].v, groups[1].v]; }
    else if(groups[0].c===3 && groups[1].c===2){ rankCategory=6; name='Full House'; scoreArr=[groups[0].v, groups[1].v]; }
    else if(isFlush){ rankCategory=5; name='Flush'; scoreArr=ranksSorted; }
    else if(isStraight){ rankCategory=4; name='Straight'; scoreArr=[highStraight]; }
    else if(groups[0].c===3){ rankCategory=3; name='Three of a Kind'; scoreArr=[groups[0].v, groups[1].v, groups[2].v]; }
    else if(groups[0].c===2 && groups[1].c===2){ rankCategory=2; name='Two Pair'; scoreArr=[Math.max(groups[0].v,groups[1].v), Math.min(groups[0].v,groups[1].v), groups[2].v]; }
    else if(groups[0].c===2){ rankCategory=1; name='One Pair'; scoreArr=[groups[0].v, groups.slice(1).map(g=>g.v)].flat(); }
    else { rankCategory=0; name='High Card'; scoreArr=ranksSorted; }
    return { rank: rankCategory, name, score: scoreArr, best: cards };
  }
  function compareEval(a,b){ if(a.rank!==b.rank) return a.rank-b.rank; for(let i=0;i<Math.max(a.score.length,b.score.length);i++){ const diff=(a.score[i]||-1)-(b.score[i]||-1); if(diff!==0) return diff; } return 0; }
  function compareHandResults(a,b){ return compareEval(a,b); }

  function clearHighlights(){ document.querySelectorAll('.card.best').forEach(el=>el.classList.remove('best')); }
  function highlightBest(containerId, bestCards){ const container=document.getElementById(containerId); const texts=bestCards.map(c=>c.rank+c.suit); [...container.children].forEach(child=>{ if(texts.includes(child.textContent)){ child.classList.add('best'); } }); }
  // Practice stats (session only)
  const stats = { hands:0, wins:0, losses:0, ties:0 };
  function updateStatsDisplay(){
    const {hands,wins,losses,ties} = stats; const winRate = hands? ((wins/hands)*100).toFixed(1):'0.0';
    const g = id=>document.getElementById(id);
    if(!g('statHands')) return; // stats section may not exist
    g('statHands').textContent = 'Hands: '+hands;
    g('statWins').textContent = 'Wins: '+wins;
    g('statLosses').textContent = 'Losses: '+losses;
    g('statTies').textContent = 'Ties: '+ties;
    g('statWinRate').textContent = 'Win%: '+winRate+'%';
  }
  function resetStats(){ stats.hands=stats.wins=stats.losses=stats.ties=0; updateStatsDisplay(); }

  // Wire buttons
  dealBtn.addEventListener('click', startHand);
  nextBtn.addEventListener('click', advance);
  foldBtn.addEventListener('click', fold);
  newBtn.addEventListener('click', newHand);
  const resetBtn = document.getElementById('resetStatsBtn');
  if(resetBtn){ resetBtn.addEventListener('click', resetStats); }
  // Keyboard shortcuts: Space=Next, N=New, F=Fold, D=Deal
  window.addEventListener('keydown', (e)=>{
    if(e.target && (e.target.tagName==='INPUT' || e.target.tagName==='TEXTAREA')) return;
    if(e.code==='Space'){ e.preventDefault(); if(!nextBtn.disabled) nextBtn.click(); }
    else if(e.key==='n' || e.key==='N'){ if(!newBtn.disabled) newBtn.click(); }
    else if(e.key==='f' || e.key==='F'){ if(!foldBtn.disabled) foldBtn.click(); }
    else if(e.key==='d' || e.key==='D'){ if(!dealBtn.disabled) dealBtn.click(); }
  });
  updateStatus('Ready. Deal to begin.');
  updatePhaseLabel();
})();
