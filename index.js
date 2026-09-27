const { 
    Client, 
    GatewayIntentBits, 
    ActionRowBuilder, 
    ButtonBuilder, 
    ButtonStyle, 
    ModalBuilder, 
    TextInputBuilder, 
    TextInputStyle, 
    EmbedBuilder 
} = require('discord.js');

const client = new Client({ 
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] 
});

const TOKEN = ''

client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}!`);
});

client.on('messageCreate', async message => {
    if (message.author.bot) return;

    if (message.content === '!reset-setup') {
        const embed = new EmbedBuilder()
            .setTitle('HWID Reset System | نظام إعادة تعيين HWID')
            .setDescription('اضغط الزر أدناه لتقديم طلب إعادة تعيين HWID.\nسيتم مراجعة الطلب من فريق الدعم.')
            .setColor(0x3498db);

        const row = new ActionRowBuilder().addComponents(
            new ButtonBuilder()
                .setCustomId('open_reset_modal')
                .setLabel('HWID Reset Request | طلب إعادة تعيين')
                .setStyle(ButtonStyle.Primary)
        );

        await message.channel.send({ embeds: [embed], components: [row] });
    }
});

client.on('interactionCreate', async interaction => {
    if (interaction.isButton() && interaction.customId === 'open_reset_modal') {
        const modal = new ModalBuilder()
            .setCustomId('hwid_modal')
            .setTitle('نموذج طلب إعادة تعيين HWID');

        // الحقل الأول: رمز الطلب (فوق)
        const hwidInput = new TextInputBuilder()
            .setCustomId('hwid_code')
            .setLabel('رمز الطلب / رمز الجهاز (HWID)')
            .setStyle(TextInputStyle.Paragraph)
            .setPlaceholder('ألصق رمز الـ HWID هنا...')
            .setRequired(true);

        // الحقل الثاني: الكي حقك (تحت)
        const keyInput = new TextInputBuilder()
            .setCustomId('license_key')
            .setLabel('الكي حقك (License Key)')
            .setStyle(TextInputStyle.Short)
            .setPlaceholder('أدخل مفتاح التفعيل هنا...')
            .setRequired(true);

        modal.addComponents(
            new ActionRowBuilder().addComponents(hwidInput),
            new ActionRowBuilder().addComponents(keyInput)
        );

        await interaction.showModal(modal);
    }

    else if (interaction.isModalSubmit() && interaction.customId === 'hwid_modal') {
        const hwidCode = interaction.fields.getTextInputValue('hwid_code');
        const licenseKey = interaction.fields.getTextInputValue('license_key');

        await interaction.reply({ 
            content: '✅ تم إرسال طلبك بنجاح! جاري معالجته.', 
            ephemeral: true 
        });
    }
});

client.login(TOKEN);