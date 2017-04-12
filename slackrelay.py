#!/usr/bin/env python
 
# Module:   slackrelay
# Date:     5th January 2017
# Author:   Cristiano Giuffrida, giuffrida at cs dot vu dot nl
 
"""slackrelay
 
Slack Relay Bot.
"""
 
__desc__ = "Slack Relay Bot"
__version__ = "0.1"
__author__ = "Cristiano Giuffrida"
__email__ = "%s, giuffrida at cs dot vu dot nl" % __author__
__url__ = "http://www.cs.vu.nl/~giuffrida"
__copyright__ = "CopyRight (C) 2017 by %s" % __author__
__license__ = "MIT"

from slackclient import SlackClient
import jason

from time import sleep
from collections import OrderedDict
import os
import re
import traceback
import argparse
import json
import requests
import logging

from websocket._exceptions import WebSocketConnectionClosedException, WebSocketTimeoutException


class LimitedSizeDict(OrderedDict):
  def __init__(self, *args, **kwds):
    self.size_limit = kwds.pop("size_limit", 100)
    OrderedDict.__init__(self, *args, **kwds)
    self._check_size_limit()

  def __setitem__(self, key, value):
    OrderedDict.__setitem__(self, key, value)
    self._check_size_limit()

  def _check_size_limit(self):
    if self.size_limit is not None:
      while len(self) > self.size_limit:
        self.popitem(last=False)

class Team:
  cache = LimitedSizeDict()

  def __init__(self, id, name):
    self.id = id
    self.name = name
    Team.cache[id] = self

  @staticmethod
  def lookup(sc, id=None):
    if id and id in Team.cache:
      return Team.cache[id]
    teamInfo = sc.api_call('team.info')
    logging.debug("Team: %s" % teamInfo)
    if not id:
      id = teamInfo['team']['id']
    return Team(id, teamInfo['team']['name'])

class Channel:
  cache = LimitedSizeDict()

  def __init__(self, tcid, id, name):
    self.id = id
    self.name = name
    Channel.cache[tcid] = self

  @staticmethod
  def lookup(sc, team, id):
    tcid = "%s~%s" % (team.id, id)
    if tcid in Channel.cache:
      return Channel.cache[tcid]
    channelInfo = sc.api_call('channels.info', channel=id)
    # if the lookup failed, try it again for a private channel
    isprivate = False
    if channelInfo['ok'] == False:
      channelInfo = sc.api_call('groups.info', channel=id)
      # hack the group info compatible to channel info, this might break silently
      if channelInfo['ok'] == True:
        channelInfo['channel'] = channelInfo['group']
        isprivate = True
    logging.debug("Channel: %s" % channelInfo)
    channelname = ""
    if isprivate:
      channelname = channelInfo['channel']['name']
    else:
      channelname = "#" + channelInfo['channel']['name']
    return Channel(tcid, id, channelname)

class User:
  cache = LimitedSizeDict()

  def __init__(self, tuid, id, name, image, fullName):
    self.id = id
    self.name = name
    self.image = image
    self.fullName = fullName
    User.cache[tuid] = self

  @staticmethod
  def lookup(sc, team, id):
    tuid = "%s~%s" % (team.id, id)
    if tuid in User.cache:
      return User.cache[tuid]
    userInfo = sc.api_call('users.info', user=id)
    logging.debug("User: %s" % userInfo)
    name = userInfo['user']['name']
    return User(tuid, id, name, userInfo['user']['profile']['image_48'], "%s@%s" % (name, team.name))

class Bot:
  def __init__(self, id, name, image):
    self.id = id
    self.name = name
    self.image = image
    self.commandPrefix = "<@%s>" % id

  @staticmethod
  def lookup(sc, team, name):
    users = sc.api_call("users.list")
    for u in users['members']:
      if 'name' in u and u['name'] == name:
          user = User.lookup(sc, team, u['id'])
          return Bot(user.id, user.name, user.image)
    err_exit(3, "Unable to find bot identity")

class Rule:
  def __init__(self, name, fTeam, fChannel, backend='echo', bURL=None):
    self.name=name
    self.fTeam=fTeam
    self.fChannel=fChannel
    self.backend=backend
    # some URLs had <> added around them
    if bURL:
      bURL = bURL.strip("<>")
    self.bURL=bURL

  def match(self, fTeam, fChannel):
    if self.fTeam != fTeam:
      logging.debug("Rule %s: Frontend team mismatch, skipping" % self.name)
      return False
    if self.fChannel != fChannel:
      logging.debug("Rule %s: Frontend channel mismatch, skipping" % self.name)
      return False
    return True

  def toDict(self):
    return {
      'name' : self.name,
      'frontend-team' : self.fTeam,
      'frontend-channel' : self.fChannel,
      'backend' : self.backend,
      'backend-url' : self.bURL,
    }

  @staticmethod
  def fromDict(d):
    return Rule(
      d.get('name'),
      d.get('frontend-team'),
      d.get('frontend-channel'),
      d.get('backend'),
      d.get('backend-url'),
    )

class Config:
  def __init__(self, file):
    self.rules = []
    self.ruleNames = set()
    self.file = file

  def addRule(self, rule):
    if not rule.name or not rule.fTeam or not rule.fChannel:
      return False
    if rule.backend == 'slack-iwh':
      if not rule.bURL:
        return False
    if rule.name in self.ruleNames:
      return False

    self.rules.append(rule)
    self.ruleNames.add(rule.name)
    return True

  def delRule(self, name):
    rulesLen = len(self.rules)
    newRules = [r for r in self.rules if r.name != name]
    self.rules = newRules
    self.ruleNames.discard(name)
    return len(self.rules) != rulesLen

  def getRules(self):
    return self.rules

  def getRuleSet(self):
    ruleSet = []
    for r in self.rules:
      ruleSet.append(r.toDict())
    return ruleSet

  def handleCommand(self, team, channel, cmd, prefix):
    ret = False
    cmd = cmd[len(prefix):]
    syntax = "Syntax: %s [rule-add json] [rule-del name] [rule-del-all] [rule-list] [help]" % prefix
    try:
      if cmd.startswith(' rule-add '):
        args = cmd[10:].strip()
        ruleDict = json.loads(args)
        ruleDict['frontend-team'] = team.name
        ruleDict['frontend-channel'] = channel.name
        rule = Rule.fromDict(ruleDict)
        logging.debug("rule-add: %s" % rule.toDict())
        ret = self.addRule(rule)
        if ret:
          self.store()
      elif cmd.startswith(' rule-del '):
        args = cmd[10:]
        ret = self.delRule(args.strip())
        if ret:
          self.store()
      elif cmd.startswith(' rule-del-all'):
        self.rules = []
        self.store()
        ret = True
      elif cmd.startswith(' rule-list'):
        return [r for r in self.getRuleSet() if r['frontend-team'] == team.name and r['frontend-channel'] == channel.name]
      elif cmd.startswith(' help'):
        return syntax
    except Exception:
      print(traceback.format_exc())
      ret = False
    if ret:
      return "Command processed succesfully"
    return "Error processing command. %s" % syntax

  def load(self):
    self.rules = []
    if not os.path.isfile(self.file):
      self.store()
    with open(self.file, mode='rb') as f:
      ruleSet = json.load(f)  
    for d in ruleSet:
      r = Rule.fromDict(d)
      if not self.addRule(r):
        err_exit(2, "Bad rule: %s" % r)
    logging.warning("Config rules: %s" % json.dumps(ruleSet, indent=4, sort_keys=True))

  def store(self):
    ruleSet = self.getRuleSet()
    with open(self.file, mode='wb') as f:
      json.dump(ruleSet, f, indent=4, sort_keys=True)

def err_exit(status, message):
  logging.error(message)
  raise SystemExit(status)

def parse_args():
  """parse_args() -> args
  
  Parse any command-line arguments..
  """

  parser = argparse.ArgumentParser(description=__desc__)
  
  parser.add_argument("-l", "--log",
    default="warning", choices=['debug', 'info', 'warning', 'error'],
    help="Log level")

  parser.add_argument("-b", "--bot",
    default="slackrelay",
    help="Bot name")

  parser.add_argument("-z", "--slave", action="store_true",
    default=False,
    help="Set this instance as a slave with private configuration")

  parser.add_argument("-f", "--config-file",
    default="slackrelay.json",
    help="Configuration file")

  parser.add_argument("-s", "--sleep-ms",
    default=100,
    help="Polling interval (ms)")

  parser.add_argument("-v", "--version",
    action='version', version=__version__)
  
  parser.add_argument("bot_user_token")
  
  args = parser.parse_args()

  return args

def connect_to_bot(bot_user_token, bot_name):
  sc = SlackClient(bot_user_token)
  if sc.rtm_connect() != True:
    err_exit(1, 'Connection Failed!')
  team = Team.lookup(sc)
  bot = Bot.lookup(sc, team, bot_name)
  logging.warning("Connected bot: %s (<@%s>)", bot.name, bot.id)
  return (bot,team,sc)

def main():
  # Parse command-line arguments
  args = parse_args()

  # Initialize logging
  logLevel = getattr(logging, args.log.upper(), None)
  logging.basicConfig(format='[%(asctime)-15s] [%(levelname)s] %(message)s', level=logLevel)
  logging.warning("Using CLI argments: %s" % vars(args))

  # Load rules from config file
  config = Config(args.config_file)
  config.load()

  (bot,team,sc) = connect_to_bot(args.bot_user_token, args.bot)

  # Process bot events
  usernamePattern = re.compile("<@[^>]+>")
  while True:
    try:
      response = sc.rtm_read()
    except (WebSocketTimeoutException, WebSocketConnectionClosedException) as e:
      logging.warning("rtm_read failed: %s" % extract_err_message(e))
      logging.warning("Reconnecting to bot..")
      (bot,team,sc) = connect_to_bot(args.bot_user_token, args.bot)
    for part in response:
      # Skip nonmessages and bot messages
      if 'type' not in part:
        logging.warning("Type not in part: %s" % str(part))
      if 'type' in part and part['type'] != 'message':
        continue
      if 'bot_id' in part:
        continue
      if 'previous_message' in part and 'bot_id' in part['previous_message']:
        continue

      # Lookup event channel
      logging.debug("New event: %s" % part)
      channel = Channel.lookup(sc, team, part['channel'])

      # Handle @slackrelay commands
      if not 'subtype' in part and part['text'].startswith(bot.commandPrefix):
        if args.slave:
          logging.warning('Skipping command "%s" (slave mode)' % part['text'])
        else:
          ret = config.handleCommand(team, channel, part['text'], bot.commandPrefix)
          sc.api_call("chat.postMessage", channel=part['channel'], text=ret, username=bot.name, icon_url=bot.image)
        continue

      # See if we have any matching rules
      rules = config.getRules()
      matchingRules = []
      for r in rules:
        if not r.match(team.name, channel.name):
          continue
        matchingRules.append(r)
      if len(matchingRules) == 0:
        continue

      # Determine user and text
      user = None
      text = None
      if 'subtype' in part:
        mtype = part['subtype']
        if mtype == 'message_deleted':
          user = User.lookup(sc, team, part['previous_message']['user'])
          text = '[DELETED] %s' % part['previous_message']['text']
        elif mtype == 'message_changed':
          user = User.lookup(sc, team, part['message']['user'])
          text = '[EDITED] %s -> %s' % (part['previous_message']['text'], part['message']['text'])
        elif mtype == 'me_message':
          part['text'] = "/me %s" % part['text']
        else:
          logging.warning("Unhandled message, skipping")
          continue
      if not user:
        user = User.lookup(sc, team, part['user'])
        text = part['text']

      for p in usernamePattern.findall(text):
        src = p
        username = p[2:-1]
        textUser = User.lookup(sc, team, username)
        text = text.replace(src, "@%s" % textUser.name, 1)
      logging.info("[%s/%s] %s: %s" % (team.name, channel.name, user.fullName, text))

      # Pass event to the backend for each matching rule
      for r in matchingRules:
        logging.debug("Processing rule: %s" % r.name)
        try:
          if r.backend == "slack-iwh":
            payload = {
              "text": text,
              "username": user.fullName,
              "icon_url": user.image
            }
            req = requests.post(r.bURL, json.dumps(payload), headers={'content-type': 'application/json'})
            req = req.ok          
          else:
            req = sc.api_call("chat.postMessage", channel=part['channel'], text=text, username=user.fullName, icon_url=user.image)   
            req = req['ok']
        except Exception:
          print(traceback.format_exc())
          req = False
        if not req:
          logging.error("Error processing rule %s" % r.name)
    sleep(float(args.sleep_ms)/1000)

if __name__ == "__main__":
   main()

